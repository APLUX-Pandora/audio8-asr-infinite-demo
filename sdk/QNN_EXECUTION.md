# QNN runtime requirements

The SDK includes matching QNN user-space libraries. Keep the complete `lib/qnn248/`
directory beside the model library. No separate QNN installation or QNN path
environment variables are needed. Compatible device BSP/drivers, FastRPC,
DSP firmware, LMS activation and Linux system libraries remain prerequisites;
see [SDK installation](README.md#device-runtime).

Use the model resources for your device and keep each audio-clock variant in
a separate package root. Files use the AIDEM format and are loaded automatically
by the matching SDK. See [model setup](../docs/MODEL_SETUP.md).

Use [Runtime](RUNTIME_API.md) for CPU, NPU device and performance options.
Unavailable devices, missing runtime components and conflicting QNN providers
are errors. A process supports one QNN backend installation. If model teardown
fails, the SDK reports an error and retains the model for cleanup. Stop using
that model for inference and keep its owner. After the backend recovers, retry
Python `model.close()` or C `a8_destroy_owned(&engine)` until it succeeds; only
then close the Runtime or load another model. A failed close is not a successful release.
