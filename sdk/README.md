# Audio8-ASR-Infinite SDK

The SDK transcribes audio using either the 160ms or the 80ms Audio8-ASR-Infinite model.

## What's included

The Python package directory is under `python/`.

| Path | Content |
| --- | --- |
| `pandora_audio8_asr_infinite/` | Python package (`from pandora_audio8_asr_infinite import ASRModel`) |
| `include/` | C header |
| `lib/` | Prebuilt native library with its QNN runtime |
| `SHA256SUMS` | Checksums of the shipped files |

The `wheels/` directory contains the shared Pandora Runtime wheel for offline installation.

## Install

<a id="device-runtime"></a>

Keep the native library with its bundled QNN runtime. See [QNN execution](QNN_EXECUTION.md) for platform dependencies and provider requirements.

In your application's activated Python 3.10–3.12 environment, from the Demo root:

```bash
python -m pip install sdk/wheels/pandora_runtime-*.whl
python -m pip install ./sdk
```

The device must pass `sudo lms check`. The SDK does not install LMS or drivers and does not download models; see [Get the model](../README.md#2-get-the-model).

## Usage

```python
from pandora_audio8_asr_infinite import ASRModel

with ASRModel.from_pretrained("models") as model:
    result = model.transcribe("examples/audio/speech.wav", language="en")
    print(result.text, result.finish_reason)
```

For 80ms, use `models/audio8-80ms`. Complete transcription defaults to Chinese. For streaming,
choose `language="zh"` or `language="en"` when opening the iterator or recording so its language is set before processing starts.

## Documentation

- [Python API](PYTHON_API.md)
- [C ABI](../docs/C_ABI.md)
- [Examples](../examples/README.md)
- [Runtime](RUNTIME_API.md)
- [Licensing](../LICENSING.md)
