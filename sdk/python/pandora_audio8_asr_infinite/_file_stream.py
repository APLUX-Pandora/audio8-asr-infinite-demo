"""Owned pull iterator for a complete file or floating PCM submission."""
import threading

from .types import ASRStateError, TranscriptionResult, TranscriptionUpdate


class FileTranscriptionStream:
    """One reserved recording, one final update, explicit early-close support."""

    def __init__(self, recording, pcm, duration, tail_tokens):
        self._model = recording._model
        self._recording = recording
        self._pcm = pcm
        self._duration = duration
        self._tail_tokens = tail_tokens
        self._offset = 0
        self._result = None
        self._closed = False
        self._operation = threading.Lock()

    @property
    def result(self):
        self._model._check_process()
        with self._operation:
            if self._result is None:
                raise ASRStateError('Final result is available after the terminal update')
            return self._result

    def __iter__(self):
        return self

    def __next__(self):
        self._model._check_process()
        if not self._operation.acquire(blocking=False):
            raise ASRStateError('File stream has an active operation')
        try:
            if self._closed:
                raise StopIteration
            try:
                return self._advance()
            except BaseException:
                self._release()
                raise
        finally:
            self._operation.release()

    def _advance(self):
        # The prepared input is owned mono16k PCM. Native inference advances
        # on demand, without a background producer or a completed-text buffer.
        end = min(self._offset + 1600, len(self._pcm))
        pcm = self._pcm[self._offset:end]
        self._offset = end
        if end < len(self._pcm):
            update = self._recording.feed(pcm)
            if update.finish_reason is None:
                return update
            result = TranscriptionResult(update.text, self._recording.language,
                                         self._duration, update.finish_reason)
        else:
            # Declare finite EOF before the last native work. This preserves
            # stop at an exact final-token cap and includes the native tail.
            result = self._recording._finish_audio(
                pcm, self._duration, tail_tokens=self._tail_tokens)
            update = self._recording._last_update
        self._result = result
        self._release()
        return TranscriptionUpdate(result.text, update.delta, result.finish_reason)

    def _release(self):
        if not self._closed:
            self._recording.close()
            self._recording = None
            self._pcm = None
            self._closed = True

    def close(self):
        self._model._check_process()
        # Wait for an in-flight next() before releasing native recording state.
        with self._operation:
            self._release()

    def __enter__(self):
        self._model._check_process()
        if self._closed:
            raise ASRStateError('File stream is closed')
        return self

    def __exit__(self, *_):
        self.close()
