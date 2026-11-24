# SDK diagnostics and resource inspection

This reference covers the retained diagnostic/resource helpers of
`pandora-audio8-asr-infinite` for both 80ms and 160ms.
Use [ASRModel v1](../sdk/PYTHON_API.md) for transcription and
[Runtime](../sdk/RUNTIME_API.md) for hardware configuration.

## Model diagnostics

Load an `ASRModel` before reading these values. The caller owns the model and
closes it after its active recording has closed and in-flight work has ended.

| Entry | Value and lifetime |
| --- | --- |
| `model.info` | Fresh dictionary containing loaded profile fields such as `clock_ms`, `sampling_rate`, `samples_per_token`, `num_delay_tokens`, `default_tail_tokens`, `roll_s` and semantic-EOT horizons. Editing it changes the returned copy. |
| `model.stats()` | Fresh dictionary of the last owned-call snapshot, with counters such as `n_tokens`, `lm_pos`, audio duration, trim/reset counts and stage milliseconds. Query after a completed operation for its snapshot. |
| `model.sdk_version` | Native library version string captured at successful loading. |

These queries retain their snapshots through model close. They do not run a
new inference call or refresh the backend while work is in flight. Transcription
results and updates follow the ownership and error rules in the main API.

## Resource inspection

Run the following in the checkout's activated `.venv` after [installation](../README.md#1-install) and [model setup](MODEL_SETUP.md).

Import the helpers from `pandora_audio8_asr_infinite`. They inspect local configuration before
inference and can be called without creating a model. File/schema errors fail
instead of selecting an unrelated package.

```python
from pandora_audio8_asr_infinite import extra_file, installed_clocks, model_files, resolve_model_dir

root = resolve_model_dir("models")
clocks = installed_clocks(root)
files = model_files(root, 160)
tokenizer_path = extra_file(root, "tokenizer")
```

| Signature | Input, return value and errors |
| --- | --- |
| `resolve_model_dir(model_dir=None, *, models_root=None)` | `model_dir` is a local path or `None` to use `A8_MODELS`. An explicit selection must contain `models.json` format_version 2. It returns the resolved absolute root as `str`. When neither explicit selection nor environment value exists, optional `models_root` permits discovery at that root or one immediate child. Missing or multiple candidates raise `A8Error`. Without `models_root`, there is no implicit discovery. |
| `installed_clocks(model_dir=None)` | Resolve a local package as above and return present clock configurations as a fresh list of integers, preferred 160 then 80. A package containing one profile reports that profile. The new models.json parser checks target/resource completeness. |
| `model_files(model_dir, clock_ms)` | Return a fresh dictionary mapping semantic resource role names to package-root-relative path strings for the requested clock. `clock_ms` must be 80 or 160 and present in the package. Invalid selections raise `ValueError` or `A8Error`. |
| `extra_file(model_dir, name)` | `name` is the configured extra resource role, such as `"tokenizer"`. Return its absolute path as `str`, or `None` when that role is undeclared. Resources declared by models.json are resolved through the package adapter. |

`A8Error` is the retained resource/C-ABI adapter exception and exposes its
integer `code`. Invalid models.json schema/path/target declarations are wrapped
as `A8Error` by these adapters. Filesystem and argument errors may propagate
with their original Python exception types. Main ASRModel loading wraps failures
as `ASRLoadError` as documented in the main reference.

These helpers locate declared resources and inspect configuration. Integrity
verification and target selection follow the [model setup](MODEL_SETUP.md) and
[package contract](MODEL_PACKAGE.md). They resolve local resources without downloading models or detecting board hardware. Explicit roots take precedence over
Demo discovery. Keep the two clock packages in separate roots and select the
same target throughout download and startup.
