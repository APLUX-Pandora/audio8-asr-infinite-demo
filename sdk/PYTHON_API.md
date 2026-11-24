# Python API

`pandora_audio8_asr_infinite` · Transcription with the 160ms and 80ms profiles.

## Quick start

Follow the repository README for [installation](../README.md#1-install) and
[model download and target selection](../README.md#2-get-the-model). Run the
following from the checkout root in its activated `.venv` after installing
`./sdk` and downloading the 160ms package.

```python
from pandora_audio8_asr_infinite import ASRModel

with ASRModel.from_pretrained("models") as model:
    result = model.transcribe("examples/audio/speech.wav", language="en")
    print(result.text, result.finish_reason)
```

For 80ms, use `models/audio8-80ms`. Pass the root containing `models.json`.
`from_pretrained()` loads local resources. Once installed, the SDK also works
from another application directory with that application's model/audio paths.
Complete transcription defaults to Chinese. This sample passes `language="en"`
because the bundled recording is in English.

## API overview

The table shows common call forms using `model` returned by
`ASRModel.from_pretrained()`; optional specialist keywords are omitted here.
[Shared parameters](#shared-parameters) define ordinary input options.
[Complete signatures](../docs/ASR_SPECIALIST_OPTIONS.md#complete-signatures)
list every accepted keyword. Optional output limits and tail padding are in
[advanced usage](#output-limits-and-tail-padding).

| Entry and common call form | Input and output timing | Return value | Runnable example or detailed contract |
| --- | --- | --- | --- |
| `ASRModel.from_pretrained(model_dir, *, runtime=None)` | Load a local 80ms or 160ms package before transcription. | `ASRModel`, supporting `with` and `close()`. | [File transcription](../examples/python/transcribe_file.py) |
| `model.transcribe(audio, *, sample_rate=None, channel=None, language=None, hotwords=None)` | Submit a complete file or PCM array; return after inference and EOF flushing. | `TranscriptionResult`. | [File](../examples/python/transcribe_file.py), [PCM](../examples/python/transcribe_pcm.py) |
| `model.transcribe_stream(audio, *, sample_rate=None, channel=None, language, hotwords=None)` | Submit a complete file or PCM array once; pull incremental text, then read `stream.result`. Input is prepared before the iterator is returned. | Owned synchronous iterator of `TranscriptionUpdate`. | [Complete-file streaming](../examples/python/transcribe_file_stream.py), [cleanup](#complete-audio-with-incremental-output) |
| `model.create_stream(*, sample_rate, channels=1, channel=None, language, hotwords=None)` | Supply PCM chunks over time with `feed()`; declare EOF with `finish()`. | Owned recording with `feed()`, `finish()` and `close()`. | [Continuous PCM](../examples/python/transcribe_realtime.py), [cleanup](#continuous-pcm-input) |
| `model.transcribe_batch(audios, *, sample_rate=None, channel=None, language, hotwords=None)` | Batch is unsupported. Language is validated before reporting unsupported batch. | Raises `ASRUnsupportedError` for a valid language. | [Capabilities and errors](#capabilities-and-errors) |
| `model.close()` | Release a model after its recording and in-flight operations have ended. Retain the model and retry this call if backend cleanup raises. | `None` on success; repeated successful close is safe. | [Ownership and errors](#ownership-and-errors) |

`model.capabilities` is immutable. Both profiles declare `streaming_input=True`,
`streaming_output=True`, `batch=False`, `selectable_languages=("zh", "en")`,
`auto_language=False` and `hotwords=True`. The retained `streaming` field means
continuous input. Free-text prompts and batch transcription are unsupported.

## Parameters

<a id="shared-parameters"></a>

### `ASRModel`

| Parameter | Type and required/default value | Effect and limits |
| --- | --- | --- |
| `model_dir` | Required local `str`/`PathLike`. | Pass the directory containing `models.json`. Download the files before loading. |
| `audio` | Required local path or NumPy `float32`/`float64` array. | File formats are WAV, FLAC and MP3, subject to the installed SoundFile/libsndfile decoder. Paths are local. PCM has shape `(samples,)` or `(samples, channels)` and finite values within the float32 range. Float amplitudes are preserved, including samples outside `[-1, 1]`. A resampled value outside the finite float32 range raises `ValueError`. Encoded bytes, URLs and integer PCM arrays are rejected. PCM16 WAV files can be decoded through the file entry. |
| `sample_rate` | Positive integer source rate in Hz. Required for PCM in `transcribe`, `transcribe_stream` and `create_stream`. | Files supply metadata; an explicit conflicting rate fails. Continuous input retains one source rate for the recording. |
| `channels` | Positive integer, default 1; continuous-input entries only. | Must match each chunk's declared layout throughout the recording. |
| `channel` | Zero-based integer source-channel index or default `None`. | Select before resampling. Without selection, mono passes through and stereo is averaged. More than two channels require explicit selection. |
| `language` | Keyword-only `"zh"` or `"en"`. Default `None` selects Chinese in `transcribe()`. Required in streaming and batch calls. | Select the native language prefix for each request. See [language selection](#language-selection). |
| `hotwords` | Default `None`; list/tuple of strings or `HotwordConfig`. | Apply token-prefix bias for this request/recording. See [hotwords](#hotwords). |
| `runtime` | Default `None`; optional caller-owned `Runtime` at loading. | Default configuration is model-owned. Advanced hardware settings and ownership are in [RUNTIME_API.md](RUNTIME_API.md). |

Input decoding, channel conversion and resampling produce mono 16kHz PCM. Empty
recordings and invalid/nonfinite samples fail. A reduced resampling numerator
or denominator above 100000 is rejected. Complete-input entries prepare the
entire recording in memory and accept at most `2**31 - 1` samples after 16kHz
conversion; available memory is an additional practical limit. Continuous
input processes chunks with persistent resampling state. Each converted chunk
must fit the native int32 sample count. The application owns recording capture,
source buffering, segmentation and presentation.

### Language selection

Both profiles use Chinese in `transcribe()` when `language` is omitted or
`None`. Streaming opens an owned request and sets its language-specific prefix
before the first update or audio chunk. Pass `"zh"` or `"en"` when opening it,
including for complete input streamed as updates. The unsupported batch entry
also requires a language for validation. Codes are case-sensitive.

| Call value | Behavior |
| --- | --- |
| Omitted or `None` | `transcribe()` selects Chinese. Streaming and batch entries raise `TypeError`. |
| `"zh"` or `"en"` | Selects Chinese or English, respectively. |
| `"auto"` or any other string | Raises `ASRUnsupportedError`. |
| Other non-string values | Raises `TypeError`. |

For a Chinese file, the audio path is enough.

```python
result = model.transcribe("speech-zh.wav")
```

### Hotwords

Pass the hints on every request that needs them. They apply throughout that
recording, including its final flush. A new request clears previous hints when
`hotwords` is omitted, `None`, or an empty list/tuple. Hints bias token prefixes;
they can affect recognition but do not guarantee that a phrase appears or is
spelled as requested. They use the tokenizer configured by the model package.

```python
result = model.transcribe(
    "examples/audio/speech.wav", language="en", hotwords=["Pandora", "Audio8"]
)
```

A directly runnable [hotword transcription example](../examples/python/transcribe_hotwords.py)
uses the bundled audio. See the [example index](../examples/README.md#hotword-transcription)
for its model, input and run command.

For explicit scoring, import the public immutable configuration.

```python
from pandora_audio8_asr_infinite import HotwordConfig

hints = HotwordConfig(
    words=("Pandora", "Audio8"),
    top_k=50,
    start_boost=6.0,
    continuation_boost=8.0,
)
with model.transcribe_stream(
        "examples/audio/speech.wav", language="en", hotwords=hints) as stream:
    for update in stream:
        print(update.delta, end="", flush=True)
    result = stream.result
```

| Hotword option | Default and allowed values |
| --- | --- |
| `words` | Required when constructing `HotwordConfig`; converted to a tuple. Up to 256 strings. Each must contain non-whitespace text, contain no NUL and use at most 1024 UTF-8 bytes. Encoded JSON must fit in 65536 bytes and each tokenizer variant in 128 tokens. A bare string is rejected. |
| `top_k` | Integer 50 by default, allowed 0 through the selected package's vocabulary size. Bool is rejected. It controls the native candidate shortlist for biasing; 0 disables the top-k restriction. |
| `start_boost` | Finite number 6.0 by default, range 0..100. Bias for the start of a hotword. |
| `continuation_boost` | Finite number 8.0 by default, range 0..100. Bias for continuing a matched prefix. |

The same `hotwords=` forms work with `create_stream()`. Supply hints when creating
the recording. Changing
application hints midway requires a new recording. Request validation reports
invalid types or bounds instead of truncating the supplied list.

### Model-specific parameters

For normal transcription, omit model tuning options. The model package selects
80ms or 160ms; the SDK manages rolling context, cache retention and recovery
defaults. Select the other profile by loading its separate model directory.

Optional [output limits and tail padding](#output-limits-and-tail-padding) are
described under advanced usage. The [specialist reference](../docs/ASR_SPECIALIST_OPTIONS.md)
lists the optional audio clock, rolling context, stable rows, semantic VAD and replay window.
The SDK uses its bundled native libraries.

## Results and cleanup

<a id="result-fields"></a>

### `TranscriptionResult`

`TranscriptionResult` is an immutable owned value.

| Field/property | Meaning |
| --- | --- |
| `text` | Final Unicode transcript, possibly empty for valid nonspeech. |
| `language` | The language used, `"zh"` or `"en"`. The Chinese default reports `"zh"`. |
| `duration_s` | Source audio duration in seconds. Complete-input entries report the whole submitted duration even when generation is capped. Continuous input reports the frames consumed so far. |
| `finish_reason` | `"stop"` for normal EOF/flush completion or `"length"` when a generation cap prevents normal completion. |
| `is_complete` | Derived property, true when `finish_reason == "stop"`. |

`TranscriptionUpdate` is also immutable and owned. `text` is the current full
snapshot, `delta` is appendable newly completed UTF-8 text and `finish_reason`
is `None` while running or `"stop"`/`"length"` at termination. Derived
`is_final` is true for a terminal reason. Empty deltas are valid.
`dataclasses.asdict()` serializes stored fields; derived properties are not
stored fields. Returned results remain valid after stream/model close.

### Complete audio with incremental output

Use `transcribe_stream()` when the complete file or PCM array is available.
Iterate to the terminal update, then read `stream.result`. Access before a
terminal update or after an early abort raises `ASRStateError`.

```python
with model.transcribe_stream("examples/audio/speech.wav", language="en") as stream:
    for update in stream:
        print(update.delta, end="", flush=True)
    result = stream.result
```

Normal iteration flushes known EOF exactly once, emits one terminal update and
releases recording ownership. An exact budget boundary at normal finite EOF
returns `stop`; a cap that prevents completion returns `length`. The cached
result remains readable after close. On early break or exception, the `with`
block closes the recording, waits for in-flight iteration and releases its
prepared audio. Early close does not start EOF inference or fabricate a final
result. The model can accept another request after the recording is released.

### Continuous PCM input

Use `create_stream()` when PCM arrives over time. Call `feed()` for each chunk,
then `finish()` when the source reaches EOF. The complete
[continuous-input script](../examples/python/transcribe_realtime.py) reads the
shipped WAV in chunks and prints updates before finishing.

```python
# pcm_chunks is an application-owned iterable of mono float PCM at 16000 Hz.
with model.create_stream(sample_rate=16000, language="en") as stream:
    for pcm in pcm_chunks:
        update = stream.feed(pcm)
        print(update.delta, end="", flush=True)
        if update.is_final:
            break
    result = stream.finish()
```

`finish()` flushes resampling and the default native tail once and
returns the final `TranscriptionResult`. Repeating the default call returns the
cached result. A different positive padding request after completion raises
`ASRStateError`. If feed already reached the generation cap, finish returns the
partial `length` result. Feed after completion raises a state error. Closing an
unfinished recording waits for current work and aborts without EOF flushing.
Always close the recording before starting another model request.

Default EOF flushing uses 17 clocks for 80ms and 14 for 160ms, with no extra
padding. The same baseline applies to `transcribe()`, `transcribe_stream()` and
`stream.finish()`. `stop` means the requested flush completed; it does not
guarantee every delayed word or punctuation mark appeared. See
[advanced tail padding](#output-limits-and-tail-padding) for the optional override.

<a id="capabilities-and-errors"></a>

### Errors

`TypeError`/`ValueError` indicate invalid inputs. `ASRError` subclasses are
`ASRLoadError`, `ASRInferenceError`, `ASRStateError` and `ASRUnsupportedError`.
`native_code` retains the native error identity when available. Validation
errors before inference leave the model reusable. After a native failure,
close and recreate the model. Input/inference errors raise exceptions instead
of returning an empty success. Batch requests with valid language raise
`ASRUnsupportedError` for both profiles.

<a id="ownership-and-errors"></a>

### Lifecycle

Use model and recording context managers or explicit `close()`. Native cleanup
failures from `model.close()` or model context-manager exit raise
`A8Error` (import it from `pandora_audio8_asr_infinite`). Its `code` field
contains the native C status, `A8_ERR_NPU` (-3) for cleanup failures. Catch
`A8Error` explicitly alongside any `ASRError` handlers. Keep the model and its
Runtime, stop inference and retry the same `model.close()` when the error
reports pending backend or memory cleanup. If the failure persists or the
error calls for a restart, shut down the owning process before starting a new
one. Load another model or close a caller-owned Runtime only after cleanup
succeeds. Each model
permits one active request/recording. Overlapping recording operations raise
`ASRStateError`. Recording close waits for in-flight work. Model close requires
that the recording has closed and native calls have returned. Application
signal handlers should request cooperative shutdown and wait for their workers.
Native calls are synchronous, so immediate cancellation is unavailable.

The default Runtime belongs to the model. A supplied Runtime belongs to the
caller and must outlive its attached models. Models and Runtime handles are
process-local; initialize them after spawn/exec and release recordings, then
models, then a caller-owned Runtime. See [Runtime ownership](RUNTIME_API.md).

If `ASRModel.from_pretrained()` fails after creating native resources and
rollback also fails, it raises `ASRLoadCleanupError`, a subclass of
`ASRLoadError`. The original initialization error is the exception cause and
`native_code` describes that error. Inspect `error.cleanup_error` for the
separate close failure. After the backend recovers, call
`error.retry_cleanup()`. It raises the close error if cleanup is still pending
and can be called again after success. The SDK retains these resources and also
retries cleanup before a subsequent load. If cleanup keeps failing, follow the
close error's restart guidance. A caller-supplied Runtime remains the caller's
responsibility.

## Advanced

[Complete examples and direct run commands](../examples/README.md) cover file,
PCM, complete-file incremental output and continuous PCM input. Select 80ms or
160ms by changing the shared scripts' `MODEL_DIR`. The supplied English WAV uses
explicit `language="en"`. For Chinese audio, `transcribe()` uses Chinese by
default. Streaming calls use explicit `language="zh"`.

Hardware configuration, supported QNN/CPU settings and Runtime lifetime are in
[RUNTIME_API.md](RUNTIME_API.md). Use [model setup](../docs/MODEL_SETUP.md) for
downloads and target selection, [model package configuration](../docs/MODEL_PACKAGE.md)
for resource roles, and [C_ABI.md](../docs/C_ABI.md) for native integration.

### Output limits and tail padding

These options are optional. Omit them for the standard recognition behavior.

| Parameter and entry | Type, default and allowed values | Effect |
| --- | --- | --- |
| `max_new_tokens` on `transcribe()`, `transcribe_stream()` and `create_stream()` | `None` means no additional generation cap. An explicit integer must be 1..`2**63 - 1`; bool and 0 are rejected. | Counts generated tokens including non-text control tokens, not characters. A cap can stop recognition early with `finish_reason="length"`. It does not add EOF padding. |
| `right_pad_text_tokens` on `transcribe()`, `transcribe_stream()` and `stream.finish()` | Integer 0 by default; nonnegative, with baseline plus extra at most 10000 clocks. Bool, float and `None` are rejected. | Adds inference clocks at EOF to the package baseline: 17 at 80ms or 14 at 160ms. More padding adds work and may allow delayed tail text to appear, without guaranteeing better recognition. |

For example, in the already activated application environment:

```python
# model is already loaded; ordinary calls can omit this option.
result = model.transcribe("speech.wav", language="en", right_pad_text_tokens=2)
```

Changing padding affects EOF processing, not the first text response.
An explicit token cap can truncate the recording. See
[results and cleanup](#results-and-cleanup) for completion and early-close rules.

### Specialist loading and context options

See the [specialist reference](../docs/ASR_SPECIALIST_OPTIONS.md) for complete
signatures, defaults and constraints for model loading and context tuning. Hardware settings
remain in `Runtime`; these controls do not replace it.

### Model diagnostics and resource inspection

| Entry | Integration use | Reference |
| --- | --- | --- |
| `model.info`, `model.stats()`, `model.sdk_version` | Inspect the loaded profile, last completed work and native version. | [SDK diagnostics](../docs/SDK_DIAGNOSTICS.md#model-diagnostics) |
| `resolve_model_dir()`, `installed_clocks()`, `model_files()`, `extra_file()` | Locate a local package and inspect its declared resource roles before application startup. | [Resource inspection](../docs/SDK_DIAGNOSTICS.md#resource-inspection) |

The first-party Web Demo maintains its own endpoint/recovery policy using
private recording diagnostics. Public integrations use `feed()` updates and
the final result from `finish()`.
