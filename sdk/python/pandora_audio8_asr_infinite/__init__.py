"""Audio8-ASR-Infinite inference with owned recording sessions."""
from __future__ import annotations
import codecs
from functools import partial, wraps
import os
import threading

import numpy as np

from ._native import (
    A8Error,
    _Native,
    extra_file as extra_file,
    installed_clocks as installed_clocks,
    model_files as model_files,
    resolve_model_dir,
)
from ._package import VOCABULARY_SIZE as _VOCABULARY_SIZE
from .audio import StreamingResampler, mono, prepare_audio, rate
from ._runtime import (
    CpuOptions as CpuOptions,
    QnnOptions as QnnOptions,
    Runtime,
    RuntimeNativeError as RuntimeNativeError,
)
from .types import (
    ASRCapabilities,
    ASRError as ASRError,
    ASRInferenceError,
    ASRLoadCleanupError,
    ASRLoadError,
    ASRStateError,
    ASRUnsupportedError,
    HotwordConfig as HotwordConfig,
    TranscriptionResult,
    TranscriptionUpdate,
    generation_limit,
    hotword_config,
)


__version__ = "1.0.0"


def _failure(error, category=ASRInferenceError):
    return category(str(error), native_code=getattr(error, 'code', None))


def _language(value):
    if not isinstance(value, str):
        raise TypeError('language must be "zh" or "en"')
    if value not in ('zh', 'en'):
        raise ASRUnsupportedError('language must be "zh" or "en"')
    return value


# A failed initialization has no caller-owned ASRModel. Keep cleanup reachable
# even if the application discards the exception. Never use an inherited lock.
_pending_loads: dict[int, ASRModel] = {}
_pending_loads_lock = threading.Lock()
_pending_loads_pid = os.getpid()


def _retry_failed_load(model):
    model._check_process()
    with _pending_loads_lock:
        if id(model) in _pending_loads:
            ASRModel.close(model)
            del _pending_loads[id(model)]


def _retry_pending_loads():
    if os.getpid() != _pending_loads_pid:
        return
    with _pending_loads_lock:
        models = tuple(_pending_loads.values())
    for model in models:
        _retry_failed_load(model)


class ASRModel:
    _capabilities = ASRCapabilities(True, ('zh', 'en'), ('zh', 'en'), False, False, True, True)

    @classmethod
    def from_pretrained(cls, model_dir, *, clock_ms=None, roll_s=28.8,
                        stable_rows=-1, semantic_vad=True, replay_max_s=10.0, runtime=None):
        model = cls.__new__(cls)
        model._native = None
        model._request = threading.Lock()
        model._failed = False
        model._stats = {}
        model._pid = os.getpid()
        model._runtime = runtime
        try:
            if runtime is not None and not isinstance(runtime, Runtime):
                raise TypeError("runtime must be a pandora_audio8_asr_infinite.Runtime")
            _retry_pending_loads()
            if model_dir is None:
                raise TypeError("model_dir must be a local model directory")
            model.model_dir = resolve_model_dir(model_dir)
            if clock_ms is not None and (isinstance(clock_ms, bool) or clock_ms not in (80, 160)):
                raise ValueError('clock_ms must be 80, 160 or None')
            if isinstance(stable_rows, bool) or not isinstance(stable_rows, int) or not -1 <= stable_rows <= 2147483647:
                raise ValueError('stable_rows must be -1 or a nonnegative int32')
            if not isinstance(semantic_vad, bool):
                raise TypeError('semantic_vad must be a bool')
            for name, value in [('roll_s', roll_s), ('replay_max_s', replay_max_s)]:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value < 0:
                    raise ValueError(f'{name} must be a finite nonnegative number')
            # Assign the owner before entering native create, including its return handoff.
            model._native = _Native.__new__(_Native)
            model._native._h = None
            model._native.__init__(model.model_dir, clock_ms, 'zh', roll_s, stable_rows,
                                   semantic_vad, replay_max_s, runtime=model._runtime)
            native = model._native
            model._info = dict(native.info)
            model._stats = native.stats()
            model.sdk_version = native._lib.a8_version().decode()
            return model
        except BaseException as error:
            model._failed = True
            try:
                if model._native is not None:
                    ASRModel.close(model)
            except BaseException as cleanup_error:
                if os.getpid() == _pending_loads_pid:
                    with _pending_loads_lock:
                        _pending_loads[id(model)] = model
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise error from cleanup_error
                if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                    raise
                raise ASRLoadCleanupError(
                    str(error), native_code=getattr(error, 'code', None),
                    cleanup_error=cleanup_error, retry_cleanup=partial(_retry_failed_load, model),
                ) from error
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise _failure(error, ASRLoadError) from error

    @property
    def capabilities(self):
        return self._capabilities

    @property
    def info(self):
        """Read-only-by-copy native profile for Infinite's advanced integrations."""
        return dict(self._info)

    def stats(self):
        """Last owned-call snapshot; querying does not race an active native call."""
        return dict(self._stats)

    def _check_process(self):
        if self._pid != os.getpid():
            raise ASRStateError("Model inherited through fork; initialize after spawn/exec")

    def _claim(self):
        self._check_process()
        if not self._request.acquire(blocking=False):
            raise ASRStateError('Model is busy; close its recording before another request')
        if self._native is None or self._failed:
            self._request.release()
            raise ASRStateError('Model is closed or requires recreation after a native failure')

    def _stream(self, *, sample_rate, channels, channel, language, prompt, hotwords, max_new_tokens):
        language = _language(language)
        if prompt is not None:
            if not isinstance(prompt, str):
                raise TypeError('prompt must be a string or None')
            raise ASRUnsupportedError('Infinite does not support a free-text prompt')
        limit = generation_limit(max_new_tokens, default=0, maximum=2**63-1)
        source_rate = rate(sample_rate)
        if isinstance(channels, bool) or not isinstance(channels, int):
            raise TypeError('channels must be a positive integer')
        if channels < 1:
            raise ValueError('channels must be positive')
        # Validate source selection without waiting for the first real chunk.
        mono(np.empty((0, channels), np.float32), channel, channels=channels)
        config = hotword_config(hotwords, max_words=256, max_bytes=1024, max_encoded_bytes=65536,
                                max_boost=100, vocabulary=_VOCABULARY_SIZE)
        stream = ASRStream(self, source_rate, channels, channel, language)
        try:
            self._native.begin_request(int(language == 'en'), limit)
            self._native.set_hotwords(config.words, top_k=config.top_k,
                start_boost=config.start_boost, continuation_boost=config.continuation_boost)
        except A8Error as error:
            if error.code == -1:
                raise ValueError(str(error)) from error
            self._failed = True
            raise _failure(error) from error
        except BaseException:
            self._failed = True
            raise
        return stream

    def create_stream(self, *, sample_rate, channels=1, channel=None, language,
                      prompt=None, hotwords=None, max_new_tokens=None):
        self._claim()
        try:
            return self._stream(sample_rate=sample_rate, channels=channels, channel=channel,
                                language=language, prompt=prompt, hotwords=hotwords,
                                max_new_tokens=max_new_tokens)
        except BaseException:
            self._request.release()
            raise

    def transcribe(self, audio, *, sample_rate=None, channel=None, language=None,
                   prompt=None, hotwords=None, max_new_tokens=None, right_pad_text_tokens=0):
        """Transcribe a complete file or PCM array, defaulting to Chinese."""
        self._claim()
        stream = None
        try:
            tail = _tail_tokens(self, right_pad_text_tokens)
            # Validate unsupported request options before opening an input file.
            language = _language('zh' if language is None else language)
            if prompt is not None:
                if not isinstance(prompt, str):raise TypeError('prompt must be a string or None')
                raise ASRUnsupportedError('Infinite does not support a free-text prompt')
            generation_limit(max_new_tokens, default=0, maximum=2**63-1)
            pcm, duration = prepare_audio(audio, sample_rate=sample_rate, channel=channel)
            if len(pcm) > 2**31-1:
                raise ValueError('Finite audio exceeds native call capacity; use a live stream')
            stream = self._stream(sample_rate=16000, channels=1, channel=None,
                                  language=language, prompt=prompt, hotwords=hotwords,
                                  max_new_tokens=max_new_tokens)
            return stream._finish_audio(pcm, duration, tail_tokens=tail)
        finally:
            if stream is None:
                self._request.release()
            else:
                stream.close()

    def transcribe_stream(self, audio, *, sample_rate=None, channel=None,
                          language, hotwords=None, max_new_tokens=None,
                          right_pad_text_tokens=0):
        """Submit complete audio and pull incremental text until stream.result."""
        from ._file_stream import FileTranscriptionStream
        self._claim()
        recording = None
        try:
            tail = _tail_tokens(self, right_pad_text_tokens)
            _language(language)
            generation_limit(max_new_tokens, default=0, maximum=2**63-1)
            pcm, duration = prepare_audio(audio, sample_rate=sample_rate, channel=channel)
            if len(pcm) > 2**31-1:
                raise ValueError('Finite audio exceeds native call capacity; use a live stream')
            recording = self._stream(sample_rate=16000, channels=1, channel=None,
                                     language=language, prompt=None, hotwords=hotwords,
                                     max_new_tokens=max_new_tokens)
            return FileTranscriptionStream(recording, pcm, duration, tail)
        except BaseException:
            if recording is None:
                self._request.release()
            else:
                recording.close()
            raise

    def transcribe_batch(self, audios, *, sample_rate=None, channel=None,
                         language, hotwords=None):
        """Batch inference is outside this delivery's scope."""
        _language(language)
        raise ASRUnsupportedError('Batch transcription is not supported')

    def close(self):
        self._check_process()
        if not self._request.acquire(blocking=False):
            raise ASRStateError('Close the active recording and wait for native calls before closing')
        try:
            if self._native is not None:
                self._native.close()
                self._native = None
            self._runtime = None
        finally:
            self._request.release()

    def __enter__(self):
        if self._native is None:raise ASRStateError('Model is closed')
        return self

    def __exit__(self, *_):self.close()


def _owned_call(function):
    @wraps(function)
    def call(self, *args, **kwargs):
        self._model._check_process()
        if not self._operation.acquire(blocking=False):
            raise ASRStateError('Recording has an active operation; wait before calling again')
        try:
            return function(self, *args, **kwargs)
        finally:
            self._operation.release()
    return call


class ASRStream:
    """One live recording; owner serializes feed, finish and close."""
    def __init__(self, model, sample_rate, channels, channel, language):
        self._operation = threading.Lock()
        self._model = model
        self.sample_rate, self.channels, self.channel = sample_rate, channels, channel
        self.language = language
        self._converter = StreamingResampler(sample_rate)
        self._decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self._pieces = []
        self._frames = 0
        self._result = None
        self._closed = False
        self._last_tokens = ()
        self._last_update = TranscriptionUpdate('', '')

    @property
    def _info(self):
        return dict(self._model._info, lang=self.language)

    @property
    def _sampling_rate(self):return 16000

    @property
    def _samples_per_token(self):return self._info['samples_per_token']

    @property
    def _clock_s(self):return self._samples_per_token / 16000

    @property
    def _tokens(self):
        """Copied native token/EOT diagnostics from the last owned operation."""
        return self._last_tokens

    def _diagnostic_stats(self):return self._model.stats()

    def _open(self):
        if self._closed:raise ASRStateError('Recording is closed')
        if self._model._failed:raise ASRStateError('Model requires recreation after native failure')

    def _execute(self, function, *args):
        try:
            return function(*args)
        except BaseException as error:
            self._model._failed = True
            if isinstance(error, A8Error):raise _failure(error) from error
            raise

    def _collect(self, tokens):
        self._last_tokens = tuple(tokens)
        try:
            delta = ''.join(self._decoder.decode(self._model._native.token_bytes(t.id))
                            for t in tokens if t.is_text)
        except UnicodeError as error:
            self._model._failed = True
            raise ASRInferenceError('Invalid UTF-8 from native token stream') from error
        if delta:self._pieces.append(delta)
        self._model._stats = self._execute(self._model._native.stats)
        self._last_update = TranscriptionUpdate(''.join(self._pieces), delta)
        return delta

    def _final(self, reason, duration):
        try:
            tail = self._decoder.decode(b'', final=reason == 'stop')
        except UnicodeError as error:
            self._model._failed = True
            raise ASRInferenceError('Incomplete UTF-8 at normal native completion') from error
        if tail:self._pieces.append(tail)
        self._result = TranscriptionResult(''.join(self._pieces), self.language, duration, reason)
        self._last_update = TranscriptionUpdate(
            self._result.text, self._last_update.delta + tail, reason)
        return self._result

    @_owned_call
    def feed(self, pcm):
        self._open()
        if self._result is not None:raise ASRStateError('Recording has already finished')
        samples = mono(pcm, self.channel, channels=self.channels)
        converted = self._converter.feed(samples)
        self._frames += len(samples)
        if len(converted) > 2**31-1:raise ValueError('PCM chunk exceeds native capacity')
        native = self._model._native
        tokens = self._execute(native.feed, converted) if len(converted) else []
        self._collect(tokens)
        if self._execute(native.request_state) == 2:
            self._final('length', self._frames / self.sample_rate)
        return self._last_update

    @_owned_call
    def _finish_audio(self, pcm, duration, *, tail_tokens=-1):
        self._open()
        native = self._model._native
        tokens = self._execute(native.finish_audio, pcm) if tail_tokens == -1 else self._execute(native.finish_audio, pcm, tail_tokens)
        self._collect(tokens)
        reason = 'length' if self._execute(native.request_state) == 2 else 'stop'
        return self._final(reason, duration)

    @_owned_call
    def finish(self, *, right_pad_text_tokens=0):
        tail_tokens = _tail_tokens(self._model, right_pad_text_tokens)
        if self._result is not None:
            if right_pad_text_tokens != 0 and tail_tokens != getattr(self, '_finished_tail', None):
                raise ASRStateError('Recording already finished; tail padding cannot be changed')
            return self._result
        self._open()
        if not self._frames:raise ValueError('Recording must contain audio before finish')
        native = self._model._native
        # EOF is declared before the converter's remaining samples reach native.
        pcm = self._converter.finish()
        tokens = self._execute(native.finish_audio, pcm) if tail_tokens == -1 else self._execute(native.finish_audio, pcm, tail_tokens)
        self._finished_tail = tail_tokens
        self._collect(tokens)
        reason = 'length' if self._execute(native.request_state) == 2 else 'stop'
        return self._final(reason, self._frames / self.sample_rate)

    @_owned_call
    def _token_bytes(self, tid):
        """Advanced byte access for the demo's token-timestamp policy."""
        self._open()
        return self._execute(self._model._native.token_bytes, tid)

    def _text_of(self, ids):return b''.join(self._token_bytes(tid) for tid in ids)

    @_owned_call
    def _eot_probs(self):
        self._open()
        return self._execute(self._model._native.eot_probs)

    @_owned_call
    def _soft_reset(self, replay_from_s):
        """Advanced replay; caller owns the text-revision/endpoint policy."""
        self._open()
        if self._result is not None:raise ASRStateError('Recording is finished')
        if isinstance(replay_from_s, bool) or not isinstance(replay_from_s, (int, float)) or not np.isfinite(replay_from_s):
            raise ValueError('replay_from_s must be a finite number')
        tokens = self._execute(self._model._native.soft_reset, replay_from_s)
        # Replay starts a new native language sequence, not a continuation byte.
        self._decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self._collect(tokens)
        if self._execute(self._model._native.request_state) == 2:
            self._final('length', self._frames / self.sample_rate)
        return list(self._last_tokens)

    def close(self):
        self._model._check_process()
        # Closing owns the same lock as feed/finish and waits for native work.
        with self._operation:
            if not self._closed:
                self._closed = True
                self._model._request.release()

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *_):self.close()



def _tail_tokens(model, right_pad_text_tokens):
    if isinstance(right_pad_text_tokens, bool) or not isinstance(right_pad_text_tokens, int):
        raise TypeError('right_pad_text_tokens must be an integer')
    baseline = model.info['default_tail_tokens']
    if not 0 <= right_pad_text_tokens <= 10000 - baseline:
        raise ValueError('right_pad_text_tokens must be nonnegative and total tail must not exceed 10000 clocks')
    return baseline + right_pad_text_tokens
