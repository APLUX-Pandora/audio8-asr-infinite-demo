# demo

Board web demo: the browser plays a video and sends its sound to the board, the board transcribes it with the SDK
engine, and the text comes back to the page over Server-Sent Events. The Help button on the page is the user manual.

How the audio gets to the model: the page decodes the video's sound
with Web Audio, resamples it to 16 kHz mono PCM16 (`static/pcm-worklet.js`; on a plain `http://` address, where browsers
do not offer AudioWorklet, the same resampler runs in a ScriptProcessorNode) and POSTs it in 100 ms chunks to
`/api/audio`. Pausing the video pauses the transcription; seeking starts a fresh session at the new position. Keep the
player unmuted: the page sends the sound it plays.

## Start

Install this Demo's `.venv` and dependencies using the [main README](../README.md#1-install). Download either variant using the complete [model setup](../docs/MODEL_SETUP.md) instructions. Start one instance using its package root:

```bash
source .venv/bin/activate
A8_CLOCK_MS=160 demo/run.sh --models models --port 8765
# Alternatively, stop the server above before using the same port for 80ms:
A8_CLOCK_MS=80 demo/run.sh --models models/audio8-80ms --port 8765
```

For background operation, use `setsid -f` before the launcher (and put the environment assignment before `setsid`), redirect stdout/stderr and retain the process identity for shutdown. The launcher uses this checkout's `.venv/bin/python`; the documented workflow activates that environment before startup, and the launcher does not fall back to global Python.

Each explicit root directly contains models.json. Without `--models`/`A8_MODELS`, a flat package or unique immediate child of checkout models/ is discovered. Multiple model roots require explicit selection. CLI `--models` overrides `A8_MODELS`; explicit relative paths use the caller's working directory. The service only offers clocks in the selected package; restart with the other root to change variants.

Open `http://<board-ip>:8765/`.

| Environment variable | Default | Meaning |
|---|---|---|
| `A8_CLOCK_MS` | the installed one (160 first) | audio clock at start-up: 160 or 80 ms; the page offers the installed clocks only |
| `A8_LANG` | en | transcription language at start-up (en / zh); the page switches it when a video is selected |
| `A8_MODELS` | automatic discovery | explicit package root; must directly contain models.json; overridden by `--models` |
| `AUDIO8_ASR_LIB` | the matched library inside the installed Python SDK | the .so to load |
| `A8_RECOVER` | reset | soft-reset policy; `off` disables it |
| `A8_RESET_AFTER_S` / `A8_RESET_QUIET_S` / `A8_RESET_BACKOFF_S` | 2 / 2 / 10 | soft-reset trigger parameters (`reset_policy.py`) |

Requirements: complete the device prerequisites and SDK installation in the
[main README](../README.md#1-install). Use a current Chrome, Edge or Firefox browser.

## Model package checks

Before loading a model or changing its configuration, the application checks the
required files and resource paths. Missing or empty resources leave the current
configuration intact. Follow the [model setup instructions](../docs/MODEL_SETUP.md)
to download and verify a complete model package.

If loading notifications are interrupted, the page checks the current server state to recover. Requests and state
confirmation have time limits, so a failed connection produces an error instead of an indefinite loading overlay.

## Using the page

1. Pick a video in the list under the player.
2. Optionally move the playhead to where you want to begin (the button then reads **Start at mm:ss**).
3. Press **Start**. The video plays with sound and the transcript appears on the right while it plays.
4. Pause the video to pause the transcription; play to continue. **Stop** ends the run.
5. Take the text with **Copy** or **Export**.

The **Help** button in the page header opens the same manual on the page.

### Controls

| Control | What it does |
|---|---|
| Video list | Selects the video (name, duration, language, "built-in" for the shipped clips). Switching stops a running transcription. |
| Start / Start at mm:ss | Plays the selected video from the playhead and starts a new transcription (clears the transcript and the statistics). |
| Stop | Stops the transcription and pauses the video. |
| Upload as Chinese / English | The language spoken in the video you are about to upload. Choose it before uploading. |
| Upload video | Uploads a video from your computer to the board; it is selected when the upload is done. Any length is accepted. MP4 (H.264 + AAC) plays in every browser. |
| Delete | Deletes the selected uploaded video. Built-in videos cannot be deleted. |
| Player | Pause / play pauses / resumes the transcription. Moving the playhead during a run continues the transcription from the new position; the transcript is kept and a "jumped to mm:ss" line marks the jump. |
| Timestamps | Each paragraph starts with its video time, e.g. `[42:10]`. Click it to play from there. |
| Audio clock | The model emits one text token per audio clock: **160 ms** (default, less compute, more headroom) or **80 ms** (text about 0.1 s sooner, twice the compute). Only installed clocks can be chosen. Changing it reloads the models (about 2 s). |
| Silence gate | On by default: until the first speech of a run, the audio is replaced by silence, so applause or noise before the speaker starts does not produce stray words. After the first speech nothing is changed. |
| Copy / Export / Clear | Copy the transcript, download it as a text file, or clear the displayed text (a running transcription continues). |

The transcription language belongs to the video: built-in videos have a fixed language, uploads use the language
chosen at upload. Selecting a video switches the models to its language (about 2 s when it changes).

### VAD settings

| Setting | Default | What it does |
|---|---|---|
| Silero threshold | 0.5 | Speech probability above which a frame counts as speech for the silence gate. Higher: less likely to open on applause, but may open slightly later. |
| Look-ahead (s) | 0.5 | How much audio before the detected start of speech is kept, so the first word is not cut. It does not delay the text while someone is talking. |
| End-of-turn horizon | 2 s | Which prediction drives the end-of-turn meter and the paragraphs: the probability that nobody speaks within the next 0.5 / 1 / 2 / 3 s. |
| End-of-turn threshold | 0.6 | Above this value the speaker is considered finished. Raise it (e.g. 0.7) if paragraphs are too short. |
| Paragraphs | on | Starts a new paragraph in the transcript at each end of turn. |

The Silero threshold and the look-ahead apply from the next Start and are shared by everyone using the board. The
end-of-turn settings apply immediately and are stored in your browser only.

### Metrics

| Metric | Meaning |
|---|---|
| Position | Video time the transcription has reached. |
| First word | Time from Start until the first word appeared. |
| Step time | Median NPU + CPU time per model step (one step per audio clock). |
| Words / Characters | Size of the transcript (characters for Chinese). |
| Silero VAD | Speech probability (the mark is the threshold), speech / silence, and the gate state: waiting for speech, or open with the seconds silenced before the speech. |
| Board DRAM | Memory used on the whole board over the last minute; it stays flat during long runs. |
| RTF | Real-time factor = step time / audio clock. Below 1 is faster than real time. |
| End of turn | The model's end-of-turn prediction for the four horizons; the bar shows the selected horizon. |

### Good to know

- **Rolling context.** The model keeps about 30 s of context. The server retains the latest 200 step timings and reset records, with a separate total reset count. Incoming audio can accumulate up to30seconds across the HTTP queue, silence gate and pending worker audio; moving audio into the worker does not reset that admission budget. The server queue also admits at most512 chunks. The browser allows at most5seconds/64 chunks waiting for upload. Exceeding either limit interrupts the recording and marks the transcript incomplete; audio is not silently skipped. Accumulated transcript text is separate from these audio limits.

`POST /api/audio?sid=N` accepts up to32000bytes per request (one second of
mono16kHz PCM16; the page normally sends3200bytes). Oversized declared bodies
are rejected before reading with413; malformed samples/lengths return400;
inactive/old/ended sessions return409; admission overflow returns429 without
accepting the block. A custom client must handle failure explicitly instead of
continuing as if all audio had been accepted. The shipped browser pauses and
uses its existing incomplete-transcript/session-stop recovery path.

On normal video EOF the browser flushes its resampler, including a final
partial PCM16 chunk, before sending `/api/end`. AudioWorklet waits for an
epoch-matched flush acknowledgement after all capture buffers; the fallback
resampler flushes synchronously. The final interpolation sample is held only
for its remaining source duration, without rounding to a full100ms chunk.
A5s capture-flush timeout marks the transcript incomplete. Seek/stop invalidates
the old flush; repeated EOF in the same epoch does not send a second end.

- **Latency.** Words appear about 1 s after they are spoken; the model listens 480 ms ahead by design.
- **Long pauses.** If the model stays silent although speech has resumed after a long pause, the demo restarts its
  context and lets it re-listen to the last seconds (a new paragraph starts there).
- **Start anywhere.** A start or a jump begins a fresh session at that point; a sentence cut by the jump may lose its
  first words.
- **One run at a time.** The board serves one transcription; a Start from any browser replaces the current run. Audio clock,
  language and gate settings are shared.
- **Slow connections.** Each event subscriber has a 256-event queue. A stalled subscriber is disconnected when that queue fills or a socket write times out. Reconnecting does not replay missed transcript events; an active browser treats a lost event connection as an interrupted recording.
- **Interrupted audio delivery.** A network error, unsuccessful audio/end HTTP request, lost event connection during transcription or 10-second request timeout pauses playback and marks the transcript **Incomplete**. Pending audio is discarded; no failed block is silently skipped or automatically replayed. Copy and download retain an incomplete marker. Reconnect, seek to before the interruption, then press Start to create a new transcription. The browser attempts a session-scoped stop immediately and again when its event connection returns, so late cleanup cannot stop a newer recording. This stops a recording; it does not unload the server's model.

RSS includes resident pages of the model's read-only memory-mapped embedding
table. As previously unseen token rows are accessed, clean file-backed RSS can
increase even when active heap/KV state stays bounded. Compare file-backed and
anonymous memory plus repeated identical requests when diagnosing growth; RSS
alone does not identify a leak. Transcript retention is a separate allocation.
- **Stopping the server.** SIGTERM/SIGINT stop the worker and wait for any synchronous native call before explicitly closing the engine. During initial model loading, shutdown is deferred until creation returns and the engine has an owner; it then closes without opening the HTTP port.

## Files

| File | Content |
|---|---|
| `demo_server.py` | HTTP + SSE server: video list, audio from the page, upload / delete, audio clock and language switch, DRAM sampling |
| `vad_gate.py` | Silero VAD start gate: only the non-speech before the first speech onset is replaced by silence |
| `reset_policy.py` | Web soft-reset trigger policy; SDK diagnostic hooks are private |
| `static/index.html` | the page, including the audio capture |
| `static/pcm-worklet.js` | 16 kHz PCM16 resampler, used by the AudioWorklet and by the page's fallback |
| `media/` | built-in English synthetic-speech videos and their language tags (`<video>.json`) |
| `run.sh` | starts the server using the installed SDK and its packaged runtime |

Uploaded videos are saved in `media/uploads/` (not committed).

The built-in videos use original sample text and synthetic speech. See [media attribution](../docs/MEDIA_ATTRIBUTION.md).

The README demonstration recording uses a separate, licensed FOSDEM 2025 talk excerpt by Lorna Mitchell,
with attribution retained. See [source, license and changes](../docs/MEDIA_ATTRIBUTION.md).


## Optional hotwords

Expand Hotwords, enable the checkbox and enter comma- or newline-separated words/phrases. Default is off and the word list is empty. Changes apply on the next Start or seek, not halfway through the current session. Advanced controls expose top-k and first/continuation boosts. Prefer a short list relevant to the content; ordinary words can be changed incorrectly.

The model package must contain models.json and the matching AIDEM model graphs and ordinary prefix resources. The Python SDK reads the tokenizer path declared in models.json. No separate tokenizer or system ICU installation is required.
See the [Python API](../sdk/PYTHON_API.md)
for limits and behavior.

## Server shutdown

SIGTERM and SIGINT stop the server and wait for the synchronous inference worker to finish before closing the native engine. New sessions are rejected during shutdown. The same cleanup runs when the HTTP port cannot be bound after model initialization.

## Inference failure and manual model reload

When inference fails, the page pauses playback, preserves the transcript and marks it incomplete.
Start and model configuration are blocked; the server rejects requests that would reuse the failed model.
Click **Reload model** to explicitly recover. The inference worker closes the old recording/model after
its current call has unwound, then creates a new instance with the selected clock/language. HTTP handlers
only queue this operation. Concurrent reload requests are rejected while loading.

Each manual click makes one model-load attempt. A load failure keeps its error visible, retains the
transcript and provides the same retry button. A successful load enables Start, keeps playback paused
and retains the old transcript's incomplete marker, including Copy/Export. Seek to before the failure
and press Start for a fresh transcription; audio is never automatically replayed after recovery.
Shutdown during loading waits for model ownership to return and explicitly closes any created instance.

`POST /api/reload` is a Web business endpoint. It queues recovery only for a failed engine; current state
and error are available from `/api/videos` and the event stream. The Python SDK's public inference API
and native library are unchanged. Transport interruptions use the incomplete-recording workflow above;
the Reload model button appears when the server reports an engine failure.

## Installed Python SDK

The repository-root `requirements.txt` installs `./sdk` into this Demo's selected `.venv`.
Web and Python examples import that installed package, without adding SDK source directories to
`sys.path`. The installed package includes its matching native library. The launcher still discovers this checkout's `models/` or uses `--models` / `A8_MODELS`.
Model/runtime setup remains separate; see [Python installation](../sdk/README.md).

## Silence-gate asset

Silero VAD v5 is bundled at `demo/assets/silero_vad.onnx` with its MIT license. It is independent of the HF model package. The semantic end-of-turn VAD remains part of the Infinite model.

## Root models.json configuration

Common resources and target graphs are resolved from `models.json` version 2. Pass the package root; see [model setup](../docs/MODEL_SETUP.md) and the [package contract](../docs/MODEL_PACKAGE.md). Only models.json format_version 2 with matching AIDEM model graphs and ordinary prefix resources is supported. Match the target to the board and runtime before starting.

## Startup signals

The Demo application temporarily blocks SIGINT/SIGTERM while constructing its
Session so shutdown cannot interrupt QNN RPC initialization. Its inference
workers inherit this application mask; the main thread restores its original mask
and owns signal handling and cleanup. A pending stop is processed after the model
owner is assigned. This policy belongs to the executable application; the installed
Python/C SDK does not alter a developer application's masks or handlers.

### Uploaded video metadata

Each new upload owns a sidecar named after its complete filename, for example
`cross.mp4.json` and `cross.mov.json`. Concurrent uploads reserve both names
without overwriting existing files. Removing an upload removes only its own
sidecar. Existing stem-only sidecars such as `cross.json` remain readable when
no per-file sidecar exists. They are retained on deletion because older videos
with different extensions may share that record. New uploads never write it.
