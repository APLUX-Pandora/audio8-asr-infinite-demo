# Audio8-ASR-Infinite

<p align="center">
  <a href="https://huggingface.co/APLUX-Pandora/Audio8-ASR-Infinite-160ms"><img src="https://img.shields.io/badge/Hugging%20Face-AUDIO8--ASR--INFINITE-E3B800?style=for-the-badge&amp;logo=huggingface&amp;logoColor=FFD21E&amp;labelColor=555555" alt="Hugging Face: Audio8-ASR-Infinite"></a>
  <a href="https://github.com/APLUX-Pandora/audio8-asr-infinite-demo"><img src="https://img.shields.io/badge/GitHub-AUDIO8--ASR--INFINITE-000000?style=for-the-badge&amp;logo=github&amp;logoColor=white&amp;labelColor=555555" alt="GitHub: Audio8-ASR-Infinite"></a>
</p>

Streaming Chinese and English speech recognition on the device NPU, with file, PCM and continuous-input transcription.

Based on [Audio8-ASR-Infinite](https://huggingface.co/Edge0/Audio8-ASR-Infinite).

**Demo recording**

https://github.com/user-attachments/assets/dc29eef2-4006-4929-9297-0d0702a7ea53

Recording includes Lorna Mitchell’s FOSDEM talk, [CC BY 2.0 BE](https://creativecommons.org/licenses/by/2.0/be/), trimmed and transcoded with live transcription. [Source, license and changes](docs/MEDIA_ATTRIBUTION.md).

## 1. Install

Clone the Demo and enter its root directory:

```bash
git clone https://github.com/APLUX-Pandora/audio8-asr-infinite-demo.git
cd audio8-asr-infinite-demo
```

### Prepare the device

If LMS is missing on Aidlux, install it with `sudo aid-pkg install aidlms-sdk` before checking activation.

Use a compatible Linux device with Aidlux LMS and the required drivers, DSP firmware and BSP/FastRPC support. The SDK includes its QNN runtime libraries; no separate QNN installation or path configuration is required.

Check the activation:

```bash
sudo lms check
```

Continue only when it returns true.

Install the system packages the Demo needs:

```bash
sudo apt install ffmpeg libsndfile1 python3-venv
```

### Install the Demo and SDK

Use Python 3.10–3.12. Create and activate the Demo environment, then install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

This installs the SDK, the Web Demo and the Hugging Face CLI. To use only the SDK in your own application, see the [SDK installation](sdk/README.md#install).

## 2. Get the model

Download the shared files and one device target. The commands below use QCS8550; for another device, use the folder in the [targets table](docs/MODEL_SETUP.md#targets). The default is 160 ms; see [80 ms setup](docs/MODEL_SETUP.md#80ms) for the other profile.

For a private model, run `hf auth login` first.

```bash
hf download APLUX-Pandora/Audio8-ASR-Infinite-160ms --local-dir models --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Audio8-ASR-Infinite-160ms --local-dir models --include "targets/qcs8550_qnn248/*"
```

## 3. Run the Web Demo

```bash
bash demo/run.sh --port 8765
```

Open `http://<device-ip>:8765/` and select a built-in video or upload one to transcribe. Stop it with `Ctrl+C`. See the [Web Demo guide](demo/README.md).

## 4. Python Usage

In the same environment, from the Demo root:

```python
from pandora_audio8_asr_infinite import ASRModel

with ASRModel.from_pretrained("models") as model:
    result = model.transcribe("examples/audio/speech.wav", language="en")
    print(result.text, result.finish_reason)
```

More in the [Python API](sdk/PYTHON_API.md) and [examples](examples/README.md).

## Documentation

- [Model setup](docs/MODEL_SETUP.md): device requirements, targets, download and folder layout
- [Python API](sdk/PYTHON_API.md): every public class, method and parameter
- [C ABI](docs/C_ABI.md): native integration
- [Examples](examples/README.md): runnable Python and C examples
- [SDK](sdk/README.md): package contents and SDK-only installation
- [Runtime](sdk/RUNTIME_API.md): hardware configuration and ownership
- [QNN execution](sdk/QNN_EXECUTION.md): runtime dependencies
- [Model package](docs/MODEL_PACKAGE.md): package layout and resource roles
- [Specialist options](docs/ASR_SPECIALIST_OPTIONS.md): advanced recognition parameters and full signatures
- [SDK diagnostics](docs/SDK_DIAGNOSTICS.md): model metadata and resource inspection
- [Model migration](docs/REAL_MODEL_MIGRATION.md): moving to the delivered model package layout
- [Media attribution](docs/MEDIA_ATTRIBUTION.md): recording sources and licenses

## License

See [LICENSING.md](LICENSING.md), [NOTICE](NOTICE) and [LICENSES](LICENSES/). Demo and example code and public interfaces use Apache-2.0. The precompiled SDK and model adaptations are subject to the Pandora Model and SDK License and applicable upstream terms.

<!-- PANDORA OWNER VIDEO -->
