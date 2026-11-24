# Examples

## Overview

| Example | What it shows |
| --- | --- |
| [python/transcribe_file.py](python/transcribe_file.py) | Complete file transcription. Final transcript text. |
| [python/transcribe_hotwords.py](python/transcribe_hotwords.py) | Request-specific recognition hints. Final transcript. |
| [python/transcribe_file_stream.py](python/transcribe_file_stream.py) | Incremental updates from a complete file. Text updates and final transcript. |
| [python/transcribe_pcm.py](python/transcribe_pcm.py) | Floating PCM with source sample rate. Final transcript text. |
| [python/transcribe_realtime.py](python/transcribe_realtime.py) | Continuous PCM and explicit EOF. Text updates and final transcript. |
| [c/transcribe_pcm.c](c/transcribe_pcm.c) | Transcribe PCM with the C ABI. Transcript on stdout and individual TOKEN IDs on stderr; exit 0 after release. |

## Before you run

Complete [Install](../README.md#1-install) and [Get the model](../README.md#2-get-the-model). Run every command from the Demo root in the activated environment. Stop the Web Demo first; examples and the Web Demo share the NPU.

The Python examples default to `models` and use the bundled English sample. For 80ms, follow the [80ms download instructions](../docs/MODEL_SETUP.md#80ms) and set the script's `MODEL_DIR` to `models/audio8-80ms`. For Chinese audio, omit `language` in complete transcription or pass `language="zh"` explicitly. Streaming examples need an explicit language.

## Python examples

### transcribe_file.py

Transcribe a complete file.

```bash
python examples/python/transcribe_file.py
```

Output (excerpt):

```text
Welcome to this speech recognition demo.
```

<a id="hotword-transcription"></a>

### transcribe_hotwords.py

Use request-specific recognition hints. The example reads the first 30 seconds of the supplied WAV.

```bash
python examples/python/transcribe_hotwords.py
```

Output (excerpt):

```text
Welcome to this speech recognition demo.
```

### transcribe_file_stream.py

Transcribe a file and read incremental text before the final result.

```bash
python examples/python/transcribe_file_stream.py
```

Output (excerpt):

```text
Welcome to this speech recognition demo.
…
```

### transcribe_pcm.py

Transcribe a floating-point PCM array decoded from the supplied WAV.

```bash
python examples/python/transcribe_pcm.py
```

Output (excerpt):

```text
Welcome to this speech recognition demo.
```

### transcribe_realtime.py

Feed continuous PCM in chunks and flush at EOF.

```bash
python examples/python/transcribe_realtime.py
```

Output (excerpt):

```text
Welcome to this speech recognition demo.
…
```

<a id="public-c-inference"></a>

## C example

### transcribe_pcm.c

Run from the Demo root. The commands convert the sample to mono 16 kHz float32 PCM.
The example prints the transcript to standard output and token IDs to standard error.

Build against the headers and prebuilt library in `sdk/`:

```bash
mkdir -p .c-example
ffmpeg -y -i examples/audio/speech.wav -f f32le -acodec pcm_f32le -ar 16000 -ac 1 .c-example/audio8-input.f32
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -Wall -Wextra -Werror -I sdk/include examples/c/transcribe_pcm.c \
  -L sdk/lib -L"$runtime_dir" -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" \
  -laudio8_asr -Wl,-rpath,"$PWD/sdk/lib" -o .c-example/audio8-c-example
.c-example/audio8-c-example models .c-example/audio8-input.f32 160 en
```

Output (excerpt)

```text
TRANSCRIPT
Welcome to this speech recognition demo.
```

See the [C ABI](../docs/C_ABI.md) for ownership and error handling.

## Reference

See the [Python API](../sdk/PYTHON_API.md) for streaming cleanup, [hotwords](../sdk/PYTHON_API.md#hotwords) for hint tuning and the [Runtime reference](../sdk/RUNTIME_API.md) for hardware settings.
