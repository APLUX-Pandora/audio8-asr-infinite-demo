#!/usr/bin/env python3
"""Web demo server (runs on the board).

One page (static/index.html): the browser plays a video (media/<id>, with sound) and captures its audio itself:
Web Audio + an AudioWorklet (static/pcm-worklet.js) resample it to 16 kHz PCM16 and POST
100 ms chunks to /api/audio. The server feeds them into the SDK engine (installed Python SDK) and pushes the text
back over Server-Sent Events. Pause = no audio = transcription pauses; seeking starts a fresh session at that position.

- Silence gate: Silero VAD (vad_gate.py) between the audio and the engine: the non-speech before the first speech onset
  becomes zeros (the engine clock keeps running); threshold and look-ahead are set from the page (next Start).
- Stream recovery: after a quiet gap, sustained sound without new text can start a fresh SDK stream
  with short audio replay. The Web transcript stays in place.
- End of turn: the model's semantic-VAD probabilities come with every token and go to the page (meter, curves,
  paragraph breaks).
- Board DRAM (sys events every 0.5 s) and per-token RTF (step time / clock) for the page's charts.
- Uploads (PUT raw body -> media/uploads/, any length, must have an audio track), deleting uploads (built-in videos are
  protected), audio clock (160 / 80 ms) and transcription language (en / zh) switches = engine reload in the worker
  thread (the page shows a loading overlay meanwhile).
- With rolling disabled (roll_s=0 in the engine) a run stops near LM position 480 (KV capacity guard).
One session at a time (a new Start resets). Standard library http.server only; ffprobe for durations and the audio check.

usage: demo/run.sh [--port 8765]   (environment variables: demo/README.md)
"""
import argparse
import collections
import json
import os
import queue
import re
import signal
import subprocess
import threading
import tempfile
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

import numpy as np  # noqa: E402

from pandora_audio8_asr_infinite import ASRModel, HotwordConfig, A8Error, resolve_model_dir  # noqa: E402
from model_package_check import PackageVerifier
from reset_policy import ResetPolicy  # noqa: E402
from vad_gate import SileroGate  # noqa: E402
from vad_worker import OwnedSileroGate  # noqa: E402

MODELS = None                         # resolved after argument parsing; --help needs no installed package

MEDIA = f"{HERE}/media"
UPLOADS = f"{MEDIA}/uploads"
STATIC = f"{HERE}/static"
MAX_POS, STOP_MARGIN = 480, 8
BACKLOG_WARN_S = 5           # warn before reaching the admission limit
MAX_AUDIO_PENDING_S = 30     # includes queued, gated and worker-pending PCM
MAX_AUDIO_CHUNKS = 512
MAX_AUDIO_CHUNK_BYTES = 32000  # at most one second of mono16k PCM16 per request
# unlimited length: the engine's LM rolls a 30 s context; without rolling (roll_s 0) the per-run capacity guard applies
VIDEO_EXT = (".mp4", ".m4v", ".mov", ".webm", ".mkv")
CLOCKS, LANGS = ("160", "80"), ("en", "zh")
MEDIA_LOCK = threading.RLock()


def media_path(vid):
    """Video id (path relative to media/) -> absolute path, or None if it escapes media/ or does not exist."""
    p = os.path.normpath(os.path.join(MEDIA, vid))      # lexical check (media files may be symlinks, e.g. a dev checkout)
    return p if p.startswith(os.path.normpath(MEDIA) + os.sep) and os.path.isfile(p) else None


def meta_of(path):
    """Each complete media filename owns a separate sidecar."""
    return path + ".json"


def legacy_meta_of(path):
    return os.path.splitext(path)[0] + ".json"


def video_lang(path):
    """Prefer the owned sidecar; read old stem-only sidecars for existing media."""
    with MEDIA_LOCK:
        metadata = meta_of(path)
        if not os.path.exists(metadata):
            metadata = legacy_meta_of(path)
        try:
            with open(metadata) as source:
                lang = json.load(source).get("lang", "zh")
        except (OSError, ValueError):
            lang = "zh"
        return lang if lang in LANGS else "zh"


def publish_upload(tmp, stem, ext, lang):
    """Reserve both names and roll back only objects acquired by this request."""
    with MEDIA_LOCK:
        k = 0
        while True:
            dst = os.path.join(UPLOADS, f"{stem}{('-' + str(k)) if k else ''}{ext}")
            try:
                os.link(tmp, dst)
            except FileExistsError:
                k += 1
                continue
            owned_meta = False
            try:
                # An orphan sidecar is reserved too; never overwrite it.
                with open(meta_of(dst), "x") as metadata:
                    owned_meta = True
                    json.dump({"lang": lang if lang in LANGS else "zh"}, metadata)
            except BaseException as error:
                os.unlink(dst)
                if owned_meta:
                    os.unlink(meta_of(dst))
                if isinstance(error, FileExistsError) and not owned_meta:
                    k += 1
                    continue
                raise
            return dst


def has_audio(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
                              path], capture_output=True, text=True, timeout=60).stdout.strip()
        return bool(out)
    except subprocess.SubprocessError:
        return False


def duration_s(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return round(float(out), 1)
    except (ValueError, subprocess.SubprocessError):
        return None


class Session:
    def __init__(self):
        self.lock = threading.Lock()
        self.closing = threading.Event()
        self.close_lock = threading.Lock()
        self.subs = []
        self.sid, self.state, self.video = 0, "idle", None
        self.offset_s, self.jump = 0.0, False            # start position of the current run in the video
        self.audio = collections.deque()                # (sid, float32 16 kHz chunk) posted by the page
        self.audio_pending_samples = 0
        self.ended, self.pending = False, None
        self.engine_error = None
        self.manual_reload = False
        self.engine_profile = None
        self.durs = {}
        self.hotwords = {"words": [], "top_k": 50, "start_boost": 6.0, "continuation_boost": 8.0}
        self.off_s = 0.0
        self.sys_hist = collections.deque(maxlen=240)      # last 120 s of [t, dram_used_mb], sent to new pages
        self.package = PackageVerifier(MODELS)
        self.clocks, self.clock_errors = [], {}
        self.gate = OwnedSileroGate(SileroGate(os.path.join(HERE, "assets", "silero_vad.onnx")))
        requested_clock = os.environ.get("A8_CLOCK_MS")
        self.clock = None
        self.lang = os.environ.get("A8_LANG", "en")
        if self.lang not in LANGS:
            raise ValueError('A8_LANG must be "zh" or "en"')
        self.asr = None
        self.policy = None
        self.model = None
        self.worker_thread = threading.Thread(target=self.worker, name="asr-worker", daemon=True)
        self.sysmon_thread = threading.Thread(target=self.sysmon, name="asr-sysmon", daemon=True)
        try:
            self.load_engine()
            self.clock = str(self.model.info["clock_ms"])
            self.clocks = [self.clock]
            self.clock_errors = {clock: "audio clock is not installed" for clock in CLOCKS if clock != self.clock}
            if requested_clock and requested_clock != self.clock:
                print(f"[demo] the {requested_clock} ms clock is not installed, using {self.clock} ms", flush=True)
            self.worker_thread.start()
            self.sysmon_thread.start()
        except BaseException:
            self.close()
            raise

    def close(self):
        """Wait for synchronous inference before releasing its native engine."""
        with self.close_lock:
            self.closing.set()
            for thread in (self.worker_thread, self.sysmon_thread):
                if thread.ident is not None:
                    thread.join()
            # Construction can fail before the engine worker starts.
            with self.lock:
                try:
                    self.close_engine()
                finally:
                    if self.gate is not None:self.gate.close()
                    self.gate = None
                self.policy = None
                self.audio.clear()
                self.audio_pending_samples = 0
                self.state = "closed"

    def load_engine(self):
        t = time.time()
        try:
            self.model = ASRModel.from_pretrained(MODELS, clock_ms=int(self.clock) if self.clock else None)
            if self.closing.is_set():
                raise RuntimeError("server is closing")
            self.asr = self.model.create_stream(sample_rate=16000, language=self.lang)
        except BaseException:
            self.close_engine()
            raise
        self.init_s = time.time() - t
        self.fs = 16000
        self.engine_profile = self.model.info
        self.spt = self.engine_profile["samples_per_token"]
        self.clock_ms = self.engine_profile["clock_ms"]
        self.n_gen = 0

    def close_engine(self):
        if self.asr is not None:
            self.asr.close()
        self.asr = None
        if self.model is not None:
            self.model.close()
            self.model = None

    # ------------------------------------------------------------ events
    def broadcast(self, ev):
        for q in list(self.subs):
            if not q.disconnected.is_set():
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    # Disconnect a stalled consumer instead of retaining an unlimited transcript.
                    q.disconnected.set()

    def info(self):
        with self.lock:
            if self.closing.is_set():
                return {"type": "info", "state": "closed"}
            return self._info()

    def _info(self):
        base = {"type": "info", "state": self.state, "engine_error": self.engine_error,
                "reload_required": self.engine_error is not None}
        profile = self.engine_profile
        if profile is None:
            return base
        roll = profile["roll_s"]
        return {**base, "clocks": list(self.clocks), "clock_errors": dict(self.clock_errors), "lang": self.lang, "clock_ms": round(self.clock_ms),
                "delay_ms": round(self.clock_ms * profile["num_delay_tokens"]),
                "max_audio_s": None if roll else round((MAX_POS - STOP_MARGIN) * self.clock_ms / 1000, 1),
                "roll_s": round(roll, 1) if roll else None,
                "init_s": round(self.init_s, 1), "state": self.state, "video": self.video, "vad": self.gate.enabled,
                "hotwords": dict(self.hotwords), "vad_params": self.gate.params, "eot_horizons_s": profile["eot_horizons_s"]}

    def videos(self):
        out = []
        for d, builtin in ((MEDIA, True), (UPLOADS, False)):
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                p = f"{d}/{f}"
                if f.lower().endswith(VIDEO_EXT):
                    if p not in self.durs:
                        self.durs[p] = duration_s(p)
                    out.append({"id": os.path.relpath(p, MEDIA), "name": f, "builtin": builtin, "duration_s": self.durs[p],
                                "lang": video_lang(p)})
        return out

    def sysmon(self):
        """Board DRAM every 0.5 s: system used = MemTotal - MemAvailable."""
        while not self.closing.is_set():
            m = {}
            for line in open("/proc/meminfo"):
                k, v = line.split(":", 1)
                m[k] = int(v.split()[0]) // 1024
            ev = {"type": "sys", "t": round(time.time(), 2), "dram_total_mb": m["MemTotal"],
                  "dram_used_mb": m["MemTotal"] - m["MemAvailable"]}
            self.dram_total = m["MemTotal"]
            self.sys_hist.append([ev["t"], ev["dram_used_mb"]])
            self.broadcast(ev)
            self.closing.wait(0.5)

    # ------------------------------------------------------------ control (HTTP threads)
    def start(self, vid, offset_s=0.0, jump=False, hotwords=None):
        """New run of `vid` from offset_s (a fresh engine session at that point of the video). jump = the page moved the
        playhead during a run (the transcript is kept and gets a time separator)."""
        config = hotwords if hotwords is not None else {"words": [], "top_k": 50, "start_boost": 6.0, "continuation_boost": 8.0}
        try:
            from hotword_settings import validate_hotwords
            config = validate_hotwords(config)
        except ValueError as e:
            return None, str(e)
        p = media_path(vid)
        if p is None:
            return None, "unknown video"
        with self.lock:
            if self.closing.is_set():
                return None, "server is closing"
            if self.state in ("reload",):
                return None, "engine is loading"
            if self.engine_error:
                return None, "model requires manual reload: " + self.engine_error
        if video_lang(p) != self.lang:                   # the page switches the language when a video is selected
            return None, f"this video is {video_lang(p)}, the engine is {self.lang}: switch first"
        with self.lock:
            if self.closing.is_set() or self.state == "reload" or self.engine_error:
                return None, "model is unavailable; wait for loading or reload the failed model"
            self.sid += 1
            self.hotwords = config
            self.video, self.offset_s, self.jump = vid, max(0.0, float(offset_s)), bool(jump)
            self.ended = False
            self.audio = collections.deque(c for c in self.audio if c[0] == self.sid)
            self.audio_pending_samples = 0
            self.state = "reset"                         # the worker resets the engine, then runs
            return self.sid, None

    def push_audio(self, sid, pcm16):
        """100 ms of 16 kHz PCM16 from the page (its own audio capture of the playing video)."""
        if not pcm16 or len(pcm16) % 2:
            return 400, "Audio must contain complete PCM16 samples"
        if len(pcm16) > MAX_AUDIO_CHUNK_BYTES:
            return 413, "Audio chunk exceeds one second"
        with self.lock:
            if self.closing.is_set() or sid != self.sid or self.state not in ("reset", "running") or self.ended:
                return 409, "Recording is not accepting audio"
            samples = len(pcm16) // 2
            if (self.audio_pending_samples + samples > MAX_AUDIO_PENDING_S * 16000
                    or len(self.audio) >= MAX_AUDIO_CHUNKS):
                return 429, "Transcription audio backlog is full; recording is incomplete"
            x = np.frombuffer(pcm16, "<i2").astype(np.float32) / 32768.0
            self.audio.append((sid, x))
            self.audio_pending_samples += samples
        return 200, None

    def end(self, sid):
        """The video reached its end: drain the remaining audio, then finish."""
        with self.lock:
            if sid == self.sid:
                self.ended = True

    def stop(self, sid=None):
        with self.lock:
            if self.closing.is_set():
                return
            # A delayed cleanup request from an interrupted browser must not stop a newer run.
            if sid is not None and sid != self.sid:
                return
            if self.state in ("reload", "error"):
                return
            stopped_sid = self.sid
            self.sid += 1
            self.state = "idle"
            self.audio.clear()
            self.audio_pending_samples = 0
            self.broadcast({"type": "state", "sid": stopped_sid, "state": "idle"})

    def set_vad(self, b):
        if "enabled" in b:
            self.gate.enabled = bool(b["enabled"])        # live: read by the gate on every frame it releases
        self.gate.configure(b.get("threshold"), b.get("preroll_s"), b.get("hangover_s"))   # from the next Start
        self.broadcast({"type": "vad", "enabled": self.gate.enabled, "params": self.gate.params})

    def configure(self, clock, lang):
        if self.closing.is_set():
            return "server is closing"
        if clock not in CLOCKS or lang not in LANGS:
            return "bad audio clock / language"
        with self.lock:
            if self.state == "reload":
                return "engine is loading"
            if self.engine_error:
                return "model requires manual reload: " + self.engine_error
        error = self.package.error(clock)             # verify before scheduling a reload or releasing the old engine
        with self.lock:
            if error:
                self.clock_errors[clock] = error
                self.clocks = [c for c in self.clocks if c != clock]
            else:
                self.clock_errors.pop(clock, None)
                self.clocks = [c for c in CLOCKS if c in self.clocks or c == clock]
        if error:
            return f"the {clock} ms model package is unavailable: {error}"
        with self.lock:
            if self.state == "reload":
                return "engine is loading"
            if self.closing.is_set() or self.engine_error:
                return "model is unavailable; reload the failed model first"
            if (clock, lang) == (self.clock, self.lang):
                return None
            self.sid += 1
            self.manual_reload = False
            self.pending, self.state = (clock, lang), "reload"
        self.broadcast({"type": "loading", "on": True, "clock_ms": clock, "lang": lang})
        return None

    def request_reload(self):
        """Queue recovery only. The inference worker owns destruction and creation."""
        with self.lock:
            if self.closing.is_set():
                return "server is closing"
            if self.state == "reload":
                return "engine is loading"
            if self.state != "error" or not self.engine_error:
                return "manual reload is available after an inference or model-load failure"
            self.sid += 1
            self.audio.clear()
            self.audio_pending_samples = 0
            self.ended = False
            self.pending = (self.clock, self.lang)
            self.manual_reload, self.state = True, "reload"
        self.broadcast(self.info())
        self.broadcast({"type": "loading", "on": True, "clock_ms": self.clock, "lang": self.lang})
        return None

    def fail_engine(self, error):
        """Keep the invalid instance quarantined until the user requests recovery."""
        with self.lock:
            self.sid += 1
            self.audio.clear()
            self.audio_pending_samples = 0
            self.ended = False
            self.pending, self.manual_reload = None, False
            self.engine_error = f"{type(error).__name__}: {error}"
            self.state = "error"
        self.broadcast(self.info())
        self.broadcast({"type": "loading", "on": False, "reload_required": True, "error": self.engine_error})

    def upload(self, name, rfile, length, lang="zh"):
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name)).strip("._") or "video.mp4"
        stem, ext = os.path.splitext(base)
        if ext.lower() not in VIDEO_EXT:
            return None, f"unsupported file type {ext or '(none)'}; use {', '.join(VIDEO_EXT)}"
        os.makedirs(UPLOADS, exist_ok=True)
        # Every request owns its staging file. Validate before publishing it;
        # hard-link creation reserves a complete final file without overwriting
        # a concurrent upload (exists-then-replace is not an atomic reservation).
        fd, tmp = tempfile.mkstemp(prefix=".upload-", suffix=".part", dir=UPLOADS)
        try:
            left = length
            with os.fdopen(fd, "wb") as f:
                while left > 0:
                    chunk = rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if left:
                return None, "upload interrupted"
            if not has_audio(tmp):
                return None, "no audio track"
            duration = duration_s(tmp)
            dst = publish_upload(tmp, stem, ext, lang)
            return {"id": os.path.relpath(dst, MEDIA), "duration_s": duration}, None
        finally:
            os.unlink(tmp)

    def delete(self, vid):
        with MEDIA_LOCK:
            p = media_path(vid)
            if p is None or not p.startswith(os.path.normpath(UPLOADS) + os.sep):
                return "only uploaded videos can be deleted"
            if self.video == vid:
                self.stop()
            # Stem-only legacy metadata may belong to other extensions. Keep
            # it as a read-only compatibility record; never claim its ownership.
            for f in (p, meta_of(p)):
                if os.path.exists(f):
                    os.remove(f)
            self.durs.pop(p, None)
            return None

    # ------------------------------------------------------------ engine (worker thread only)
    def worker(self):
        while not self.closing.is_set():                   # keep the engine thread alive across unexpected errors
            try:
                self.work()
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                self.fail_engine(e)

    def work(self):
        # pend = gated samples not yet fed; fed = samples fed to the engine in this run. The audio arrives from the page in
        # 100 ms chunks (self.audio) while the video plays.
        fed, pend, steps, t_start, first_char = 0, np.zeros(0, np.float32), collections.deque(maxlen=200), 0.0, None
        stream_start, stream_chars = 0, 0
        last_char, join_replay = "", False
        flushed, warned = False, False
        while not self.closing.is_set():
            with self.lock:
                state, sid, ended = self.state, self.sid, self.ended
                chunks = []
                if state == "running":
                    while self.audio:
                        c = self.audio.popleft()
                        if c[0] == sid:
                            chunks.append(c[1])
            if state == "reload":
                self.reload()
                continue
            asr = self.asr
            if state == "reset":
                asr.close()
                with self.lock:
                    off_s, jump = self.offset_s, self.jump
                    hotwords = dict(self.hotwords)
                hints = HotwordConfig(tuple(hotwords["words"]), hotwords["top_k"],
                                      hotwords["start_boost"], hotwords["continuation_boost"])
                options = dict(sample_rate=self.fs, language=self.lang, hotwords=hints)
                self.asr = self.model.create_stream(**options)
                self.policy = ResetPolicy(self.fs, self.spt, roll_s=self.engine_profile["roll_s"])
                stream_start, stream_chars = 0, 0
                last_char, join_replay = "", False
                self.gate.reset()
                self.n_gen = 0
                self.off_s = off_s
                fed, pend, steps, t_start, first_char = (0,
                                                              np.zeros(0, np.float32), collections.deque(maxlen=200), time.time(), None)
                flushed, warned = False, False
                with self.lock:
                    if self.sid == sid and self.state == "reset":
                        self.state = "running"
                        self.broadcast({"type": "reset", "sid": sid, "offset_s": round(off_s, 2), "jump": jump, "hotwords": hotwords})
                        self.broadcast({"type": "state", "sid": sid, "state": "running"})
                continue
            if state != "running":
                time.sleep(0.02)
                continue
            for block in chunks:                          # page audio -> VAD gate (output lags by the gate look-ahead)
                pend = np.concatenate([pend, self.gate.process(block)])
            if not warned and pend.size > BACKLOG_WARN_S * self.fs:   # audio is kept (never drop speech), only reported
                print(f"[demo] the engine is {pend.size / self.fs:.0f} s behind the video (NPU busy?)", flush=True)
                warned = True
            if ended and not flushed and not chunks:      # end of the video: release the gate's look-ahead
                pend = np.concatenate([pend, self.gate.flush()]); flushed = True
            done, reason = False, None
            if not asr._info["roll_s"] and asr._diagnostic_stats()["lm_pos"] >= MAX_POS - STOP_MARGIN:
                done, reason = True, "limit"
            elif pend.size >= self.spt or (flushed and pend.size):
                # Keep recovery windows aligned across incoming HTTP chunks.
                t = time.time()
                chunk, pend = pend[:self.spt], pend[self.spt:]
                update = asr.feed(chunk)
                fed += chunk.size
                replay = self.policy.observe(chunk, update.delta, fed)
                recovery = None
                if replay is not None:
                    with self.lock:
                        if self.sid != sid or self.state != "running" or self.closing.is_set():
                            continue
                    restart_at = time.monotonic()
                    asr.close()
                    asr = self.asr = self.model.create_stream(**options)
                    stream_start = fed - replay.size
                    join_replay = bool(last_char and not last_char.isspace() and self.lang == "en")
                    # Replay starts after the last text sent to the browser.
                    # Only the new stream's text is published at this boundary.
                    update = asr.feed(replay)
                    recovery = self.policy.record(fed, replay.size)
                    recovery["replay_wall_s"] = round(time.monotonic() - restart_at, 3)
                with self.lock:
                    if self.sid == sid:
                        self.audio_pending_samples = max(0, self.audio_pending_samples - chunk.size)
                stream_chars = len(update.text)
                piece = update.delta
                if piece and join_replay:
                    if piece[0].isalnum():
                        piece = " " + piece
                    join_replay = False
                if piece:
                    last_char = piece[-1]
                toks = asr._tokens
                if toks:
                    steps.append((time.time() - t) / len(toks))
                if first_char is None and any(asr._token_bytes(k.id) for k in toks):
                    first_char = time.time() - t_start
                self.emit(sid, toks, piece, fed, steps, first_char, eot=self.eot(toks),
                          stream_start=stream_start, recovery=recovery)
                continue
            elif ended and flushed:
                done, reason = True, "end"
            if done and fed == 0 and reason == "end":
                asr.close()
                with self.lock:
                    if self.sid == sid and self.state == "running":
                        self.state = "done"
                        self.audio_pending_samples = 0
                        self.audio.clear()
                        self.broadcast({"type": "state", "sid": sid, "state": "done", "reason": "empty"})
                continue
            if done:
                result = asr.finish()
                toks = asr._tokens
                piece = result.text[stream_chars:]
                if piece and join_replay and piece[0].isalnum():
                    piece = " " + piece
                self.emit(sid, toks, piece, fed, steps, first_char, eot=self.eot(toks),
                          stream_start=stream_start)
                with self.lock:
                    if self.sid == sid and self.state == "running":
                        self.state = "done"
                        self.audio_pending_samples = 0
                        self.audio.clear()
                        self.broadcast({"type": "state", "sid": sid, "state": "done", "reason": reason,
                                        "finish_reason": result.finish_reason,
                                        "audio_s": round(self.off_s + fed / self.fs, 2)})
                continue
            time.sleep(0.01)

    def reload(self):
        with self.lock:
            clock, lang = self.pending
            manual = self.manual_reload
        old = (self.clock, self.lang)
        err = None
        loaded = False
        if not self.close_before_reload():
            return
        attempts = [(clock, lang)] if manual else [(clock, lang), old]
        for c, l in attempts:                           # manual recovery makes exactly one attempt
            if self.closing.is_set():
                return
            try:
                self.clock, self.lang = c, l              # audio clock / language are chosen at engine creation
                self.load_engine()
                self.gate.reset()
                loaded = True
                break
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
                print(f"[demo] engine load {c} ms/{l} failed: {err}", flush=True)
                if not self.close_before_reload():
                    return
        if self.closing.is_set():
            return
        if not loaded:
            self.fail_engine(RuntimeError(err or "model reload failed"))
            return
        with self.lock:
            self.pending, self.video, self.state = None, None, "idle"
            self.manual_reload, self.engine_error = False, None
            self.audio.clear()
            self.audio_pending_samples = 0
            self.ended = False
        print(f"[demo] engine reloaded in {self.init_s:.1f}s, {self.clock} ms clock, lang {self.lang}", flush=True)
        self.broadcast(self.info())
        self.broadcast({"type": "loading", "on": False, "error": err})

    def close_before_reload(self):
        try:
            self.close_engine()
        except Exception as error:
            self.fail_engine(RuntimeError(
                f"Model cleanup failed: {error} "
                "Retry Reload Model after backend recovery. If cleanup still fails, restart the Demo process."
            ))
            return False
        return True

    @staticmethod
    def eot(toks):
        """P(class 0 = no speech within each horizon) after the newest token (semantic VAD, computed by the SDK)."""
        return [round(float(v), 3) for v in toks[-1].eot] if toks else None

    def emit(self, sid, toks, piece, fed, steps, first_char, eot=None, *, stream_start=0, recovery=None):
        a = self.asr
        self.n_gen += len(toks)
        # Text comes from the public SDK. Token diagnostics serve the charts.
        ms = 1000 * np.fromiter(steps, dtype=np.float64) if steps else np.zeros(1)
        # video time of the first text token of this piece (its row time minus the model delay), for paragraph timestamps
        t_first = None
        for k in toks:
            if a._token_bytes(k.id).strip():
                t_first = round(self.off_s + stream_start / self.fs
                                + max(0.0, k.audio_t - self.clock_ms * a._info["num_delay_tokens"] / 1000), 2)
                break
        event = {"type": "text", "sid": sid, "piece": piece, "audio_s": round(self.off_s + fed / self.fs, 2), "t_first": t_first, "tokens": self.n_gen,
                        "lm_pos": a._diagnostic_stats()["lm_pos"], "step_ms": round(float(ms[-1]), 1), "step_ms_median": round(float(np.median(ms)), 1),
                        "rtf": round(float(ms[-1]) / self.clock_ms, 3), "rtf_median": round(float(np.median(ms)) / self.clock_ms, 3),
                        "first_char_s": None if first_char is None else round(first_char, 2), "eot": eot, "resets": self.policy.reset_count, **self.gate.stats()}
        if recovery is not None:
            event["recovery"] = recovery
        # Native calls above may overlap a stop or replacement. Check and
        # enqueue under the same lock as the session transition.
        with self.lock:
            if self.sid == sid and self.state == "running":
                self.broadcast(event)


S = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._file(f"{STATIC}/index.html", "text/html; charset=utf-8")
        if p in ("/pandora-mark.svg", "/favicon.ico"):
            return self._file(f"{STATIC}/pandora-mark.svg", "image/svg+xml")
        if p == "/logo.png":
            return self._file(f"{STATIC}/logo.png", "image/png")
        if p == "/pcm-worklet.js":
            return self._file(f"{STATIC}/pcm-worklet.js", "text/javascript; charset=utf-8")
        if p == "/api/videos":
            return self._json({"videos": S.videos(), **S.info()})
        if p == "/api/events":
            return self._events()
        if p.startswith("/media/"):
            f = media_path(urllib.parse.unquote(p[len("/media/"):]))
            if f and f.lower().endswith(VIDEO_EXT):
                ext = os.path.splitext(f)[1].lower()
                return self._file(f, {".webm": "video/webm", ".mkv": "video/x-matroska", ".mov": "video/quicktime"}.get(ext, "video/mp4"))
        self.send_error(404)

    def do_PUT(self):
        p, q = self.path.split("?")[0], urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if p == "/api/upload":
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return self._json({"error": "empty upload"}, 400)
            res, err = S.upload(q.get("name", ["video.mp4"])[0], self.rfile, n, q.get("lang", ["zh"])[0])
            return self._json(res if err is None else {"error": err}, 200 if err is None else 400)
        self.send_error(404)

    def do_POST(self):
        p = self.path.split("?")[0]
        if p == "/api/audio":                           # raw PCM16 body, ?sid=<run>
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self.close_connection = True
                return self._json({"error": "Invalid audio Content-Length"}, 400)
            if n <= 0 or n % 2 or n > MAX_AUDIO_CHUNK_BYTES:
                self.close_connection = True  # Do not allocate/read an unbounded body.
                return self._json({"error": "Audio request must contain up to one second of PCM16"},
                                  413 if n > MAX_AUDIO_CHUNK_BYTES else 400)
            data = self.rfile.read(n) if n > 0 else b""
            if len(data) != n:
                return self._json({"error": "Incomplete audio request"}, 400)
            try:
                sid = int(q.get("sid", ["-1"])[0])
            except ValueError:
                sid = -1
            status, error = S.push_audio(sid, data)
            return self._json({"error": error} if error else {}, status)
        b = self._body()
        if p == "/api/start":
            sid, err = S.start(b.get("video", ""), b.get("offset_s", 0.0), b.get("jump", False), b.get("hotwords"))
            return self._json({"sid": sid} if err is None else {"error": err}, 200 if err is None else 409)
        if p == "/api/end":
            S.end(b.get("sid"))
            return self._json({})
        if p == "/api/stop":
            S.stop(b.get("sid"))
            return self._json({})
        if p == "/api/config":
            err = S.configure(str(b.get("clock_ms")), str(b.get("lang")))
            return self._json({} if err is None else {"error": err}, 200 if err is None else 409)
        if p == "/api/reload":
            err = S.request_reload()
            return self._json({} if err is None else {"error": err}, 200 if err is None else 409)
        if p == "/api/vad":
            S.set_vad(b)
            return self._json({})
        if p == "/api/delete":
            err = S.delete(b.get("video", ""))
            return self._json({} if err is None else {"error": err}, 200 if err is None else 400)
        self.send_error(404)

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.connection.settimeout(15)
        q = queue.Queue(maxsize=256)
        q.disconnected = threading.Event()
        S.subs.append(q)
        try:
            self.wfile.write(f"data: {json.dumps(S.info())}\n\n".encode())
            if S.state == "reload":
                self.wfile.write(f"data: {json.dumps({'type': 'loading', 'on': True})}\n\n".encode())
            if S.sys_hist:
                h = {"type": "sys_hist", "dram_total_mb": S.dram_total, "pts": list(S.sys_hist)}
                self.wfile.write(f"data: {json.dumps(h)}\n\n".encode())
            self.wfile.flush()
            while not S.closing.is_set() and not q.disconnected.is_set():
                try:
                    ev = q.get(timeout=10)
                    self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            S.subs.remove(q)

    def _file(self, path, ctype):
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else max(0, size - int(b))
            end = int(b) if a and b else size - 1
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    global S, MODELS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--models", default=os.environ.get("A8_MODELS"),
                    help="package root containing models.json; default: discover this demo models directory")
    a = ap.parse_args()
    try:
        MODELS = resolve_model_dir(a.models, models_root=f"{ROOT}/models")
    except A8Error as error:
        ap.error(str(error))
    print(f"[demo] model package: {MODELS}", flush=True)
    srv = None
    previous = {}
    stop_requested = False

    def interrupt(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        # Let synchronous native creation return its handle before unwinding.
        # Raising here during ctypes.create can lose an already allocated handle.
        if S is None:
            return
        # Stop accepting work immediately; unwind on the server's main thread.
        if S is not None:
            S.closing.set()
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt

    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, interrupt)
        # Application-owned startup policy: avoid interrupting vendor RPC setup.
        # Background inference threads inherit these blocked shutdown signals;
        # the main thread restores its original mask and owns shutdown handling.
        startup_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        try:
            S = Session()
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, startup_mask)
        if stop_requested:
            raise KeyboardInterrupt
        print(f"[demo] engine ready in {S.init_s:.1f}s, {S.clock} ms clock, lang {S.lang}; http://0.0.0.0:{a.port}/", flush=True)
        srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
        srv.daemon_threads = True
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        if srv is not None:
            srv.server_close()
        if S is not None:
            S.close()
            print("[demo] engine closed; workers stopped", flush=True)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
