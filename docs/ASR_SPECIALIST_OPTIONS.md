# ASR specialist options

Ordinary transcription uses the [Python API](../sdk/PYTHON_API.md) without
overriding these options. The installed model package and SDK supply the defaults.
This reference documents accepted specialist keywords for integrations that need
them; it does not require applications to configure them.

## Complete signatures

These are the complete accepted signatures, including specialist options omitted
from the main guide's common call forms.

```python
ASRModel.from_pretrained(
    model_dir, *, clock_ms=None, roll_s=28.8,
    stable_rows=-1, semantic_vad=True, replay_max_s=10.0, runtime=None,
)
model.transcribe(
    audio, *, sample_rate=None, channel=None, language=None, prompt=None,
    hotwords=None, max_new_tokens=None, right_pad_text_tokens=0,
)
model.transcribe_stream(
    audio, *, sample_rate=None, channel=None, language, hotwords=None,
    max_new_tokens=None, right_pad_text_tokens=0,
)
model.create_stream(
    *, sample_rate, channels=1, channel=None, language, prompt=None,
    hotwords=None, max_new_tokens=None,
)
stream.finish(*, right_pad_text_tokens=0)
```

These are reference signatures, not an executable example. Ordinary input,
language, hotword and result contracts are in the main guide.
[Output limits and tail padding](../sdk/PYTHON_API.md#output-limits-and-tail-padding)
document `max_new_tokens` and `right_pad_text_tokens`.

## Loading and context controls

The following keywords apply to `ASRModel.from_pretrained()`.

| Keyword | Type, default and allowed values | Purpose and limits |
| --- | --- | --- |
| `clock_ms` | `None`, 80 or 160; bool is rejected. | Omission selects an installed model profile, preferring 160 when multiple profiles are present. An explicit profile must exist in that package. The two HF packages are normally kept in separate roots, so no override is needed. This is not the source sample rate or the size of a `feed()` chunk. |
| `roll_s` | Finite nonnegative number, default 28.8 seconds. | Controls the rolling model context. 0 disables rolling; fixed KV capacity still applies. After rounding to clocks, the window must fit in 480 rows and hold the retained prefix/header plus a full trim interval (19 rows at 160 ms or 38 at 80 ms) and at least one recent row. Values outside that range raise an error. Keep the default for ordinary long-running transcription. |
| `stable_rows` | Integer -1 by default, or 0 to 13 at 160 ms and 0 to 25 at 80 ms. Booleans are rejected. | -1 retains 9 rows at 160 ms or 18 at 80 ms. Values below the fixed prefix size (8 or 16 rows, respectively) retain the full prefix. It does not declare transcript text final or set a text-stability threshold. |
| `semantic_vad` | Bool, default `True`. | Computes native semantic end-of-turn probabilities. It does not filter incoming silence or automatically segment a public recording. The first-party Demo uses its own endpoint policy; ordinary integrations can leave this enabled. |
| `replay_max_s` | Finite nonnegative number, default 10.0 seconds. | Limits history used by the SDK's internal soft-reset/replay path. Cached audio features support recovery; this option alone does not trigger recovery, delay incoming audio or define a public recording duration limit. |

These options can affect model context, resource use or endpoint diagnostics.
Use the default behavior unless the integration has a specific need and validates
its output. Private Demo recovery hooks are not public transcription entry points.

## Unsupported prompt keyword

The accepted `prompt` keyword on `transcribe()` and `create_stream()` defaults to
`None`. Free-text prompts are unsupported: any string, including an empty
string, raises `ASRUnsupportedError`; another non-None type raises `TypeError`.
Use `hotwords` for supported recognition hints. `transcribe_stream()` does not
accept a `prompt` keyword.

## Hardware and ownership

CPU, performance and NPU selection belong to [Runtime](../sdk/RUNTIME_API.md).
The [main API ownership rules](../sdk/PYTHON_API.md#ownership-and-errors) apply
to all options above. Finish or close an active recording before closing its model.
