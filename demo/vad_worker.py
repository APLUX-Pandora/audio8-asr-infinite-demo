"""Serialize the Web Demo speech gate on its own worker."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading


class OwnedSileroGate:
    def __init__(self, gate):
        self._pid = os.getpid()
        self._lock = threading.RLock()
        self._gate = gate
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio8-vad")
        self._closed = False
        self._segment_snapshot = None
        self._stats_snapshot = None

    def _check_process(self):
        if os.getpid() != self._pid:
            raise RuntimeError('VAD worker inherited through fork; initialize after spawn/exec')

    def __getattr__(self, name):
        return getattr(self._gate, name)

    def _invoke(self, fn):
        self._check_process()
        with self._lock:
            if self._closed:
                raise RuntimeError('VAD worker is closed')
            return self._pool.submit(fn).result()

    def _call(self, method, *args, **kwargs):
        def call():
            try:
                result = getattr(self._gate, method)(*args, **kwargs)
            except BaseException:
                self._segment_snapshot = self._stats_snapshot = None
                raise
            if method in ('process', 'flush', 'reset', 'configure'):
                self._segment_snapshot = self._gate.segment()
                self._stats_snapshot = self._gate.stats()
            return result
        return self._invoke(call)

    @property
    def enabled(self): return self._invoke(lambda: self._gate.enabled)

    @enabled.setter
    def enabled(self, value):
        def update():
            self._gate.enabled = bool(value)
            self._stats_snapshot = self._gate.stats()
        self._invoke(update)

    def process(self, samples): return self._call('process', samples)
    def flush(self): return self._call('flush')
    def configure(self, *args, **kwargs): return self._call('configure', *args, **kwargs)
    def reset(self): return self._call('reset')
    def segment(self):
        # A process call has already joined the owned worker. Read its immutable
        # state snapshot without another cross-thread round trip per audio chunk.
        self._check_process()
        with self._lock:
            if self._closed:
                raise RuntimeError('VAD worker is closed')
            if self._segment_snapshot is None:
                return self._call('segment')
            return self._segment_snapshot
    def stats(self):
        self._check_process()
        with self._lock:
            if self._closed:
                raise RuntimeError('VAD worker is closed')
            if self._stats_snapshot is None:
                return self._call('stats')
            return dict(self._stats_snapshot)
    def speech_recent(self, *args, **kwargs): return self._call('speech_recent', *args, **kwargs)

    def close(self):
        self._check_process()
        with self._lock:
            if self._closed:
                return
            self._pool.shutdown(wait=True)
            self._gate = None
            self._closed = True
