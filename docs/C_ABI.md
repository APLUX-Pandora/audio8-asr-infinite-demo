# C ABI

`sdk/include/audio8_asr.h` · `sdk/lib/libaudio8_asr.so` · Audio8 speech recognition and Runtime integration.

<a id="target-and-linking"></a>

## Build and link

Follow the [SDK installation](../sdk/README.md#install) in an activated Python environment.

From the Demo root, compile against the shipped header and library; the library carries its QNN runtime:

```bash
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -I sdk/include your_app.c -L sdk/lib -L"$runtime_dir" -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" -laudio8_asr -Wl,-rpath,'$ORIGIN/sdk/lib' -o your_app
```

For deployments without Python, make the shared library from the Runtime wheel available to the dynamic loader.

The prebuilt library is Linux AArch64, with packaged QNN user-space libraries and LMS plus compatible board BSP/drivers, FastRPC and firmware.
It does not run natively on Windows, macOS or x86 Linux. Required Linux symbol versions include GLIBC 2.34
and GLIBCXX 3.4.30; install the platform-supported C++ runtime, not a library copied from another OS.
Direct dependencies include `libaidlms.so`, `libstdc++.so.6`, `libm.so.6`, `libgcc_s.so.1`, `libc.so.6`
and the AArch64 loader. ICU code and Unicode data are embedded. QNN user-space libraries are included beside the model library in `lib/qnn248/`. FastRPC, drivers and firmware remain device prerequisites. The packaged System library also needs the system `libatomic.so.1`; host Stubs need BSP `libcdsprpc.so`. DSP architectures v68/v73/v75 need firmware `libc++.so.1` and `libc++abi.so.1`. These device components are not supplied by the SDK.

Build the [complete C99 example](../examples/c/transcribe_pcm.c) against the
same delivered .so. The [compile and run commands](#complete-c99-transcription-example)
cover both profiles and PCM preparation. The SDK .so has no RPATH/RUNPATH;
configure your executable's library search path and use `ldd` on the board to
diagnose device dependencies. Keep `libaudio8_asr.so` and the complete adjacent `qnn248/` tree together. The SDK selects the packaged Stub/Skel using the device's actual HTP architecture. No separate QNN installation or QNN path exports are needed. Missing libraries and conflicting QNN providers are rejected rather than resolved from the board. Different SDK/QNN installations in one process are unsupported. Prepare [device prerequisites](../sdk/README.md#device-runtime) before compiling or running examples.

## Lifecycle

```text
a8_default_options → a8_create → a8_reset → a8_feed / a8_read_tokens → a8_finish → a8_destroy_owned
```

1. Fill `a8_options` using `a8_default_options`, then set the desired clock/language and supported options.
2. Call `a8_create` with a directory directly containing models.json. `NULL` means failure; immediately
   read `a8_create_error()` (thread-local). No engine may be used on failure.
3. Call `a8_reset` for the session; optionally configure hotwords before feeding audio.
4. Feed audio and drain all queued tokens. Calls are synchronous, and one engine is used by one thread at a time.
5. Call `a8_finish` once, then drain its final tokens. To feed or soft-reset again, first start a session with reset.
6. Call `a8_destroy_owned(&engine)` after each successful creation, including application errors and interruption. On backend or memory cleanup failure it returns a negative status and leaves `engine` intact. Read `a8_last_error(engine)`, keep that owner, and retry the same close when the error reports pending cleanup. Keep the pending engine out of inference. If cleanup keeps failing or the error calls for a restart, shut down the owning process before reloading. Successful cleanup clears the slot; empty cleanup succeeds.

The C example checks errors and reaches a shared cleanup path. Its
SIGTERM/SIGINT handler records a request only. It waits for native creation/inference to return
before unwinding and destroying. Do not throw from a signal handler, destroy from a competing thread, or rely on
process exit to reclaim DSP resources. A SIGKILL/crash cannot run application cleanup. Graceful interruption may
wait for the current synchronous native call; it is not an immediate cancel API.

The SDK owns the engine and its graphs/caches. PCM, options, output buffers and result structs are supplied by the
caller. Do not free native error/version string pointers. Copy an error message before making another operation
on the same engine. Media decoding and playback are outside the C ABI; native inference calls are synchronous.

### Options and data structures

Use the declarations and field comments in the header as the exact layout; do not repack/reorder structs.

| Structure | Fields and units |
| --- | --- |
| `a8_options` | `clock_ms` defaults to 160. Use 80 for the 80 ms profile or 0 to use the clock in the model package. `lang` defaults to `A8_LANG_ZH` and also accepts `A8_LANG_EN`. `roll_s` defaults to 28.8 seconds. Set it to 0 to disable rolling. A positive window is converted to processing steps and rounded to a whole step using the floating-point rounding mode that the model worker inherits from the calling thread at creation. The default mode rounds to the nearest step, with ties to even. The rounded window may contain at most 480 steps (rows). Creation fails with an invalid-argument error if it exceeds that limit. It must hold the prefix and header plus a full trim interval (19 rows at 160 ms or 38 at 80 ms) and one recent row. `stable_rows` accepts -1 for the defaults (9 or 18) or 0 through the prefill size (13 or 25, respectively). The full prefix is always retained. `semantic_vad` accepts 1 (default) or 0. `replay_max_s` defaults to 10 seconds and must be nonnegative and within the context and replay budget. |
| `a8_token` | `id` int32; `is_text` int32 flag; `audio_t` float seconds from session start excluding synthetic padding; `eot[4]` no-speech probabilities at 0.5/1/2/3 seconds, zero when disabled. EOS is not emitted. |
| `a8_info` | Sampling rate, samples/clock, clock/language, four horizon seconds, delay-token count, pad ID, default tail clocks and rolling seconds. Read after creation; use `samples_per_token/sampling_rate` for clock duration. |
| `a8_stats` | Audio seconds; emitted token count; absolute LM position; trim/reset counts; cumulative stage milliseconds. Full field names, integer widths and units are defined in [the public header](../sdk/include/audio8_asr.h). Python `stats()` returns a copy of these diagnostic fields; task results are documented under [Transcription](../sdk/PYTHON_API.md#result-fields). |

Do not change an engine's creation options in-place. Use the package for the selected clock/SoC. The 80ms and
160ms resources remain independent, with complete manifests and checksums; see [model placement](MODEL_SETUP.md).

## Functions

Functions returning `int` use a nonnegative success/count and negative `A8_ERR_*` errors unless noted.
Read `a8_last_error(engine)` immediately on failure.

| Function | Parameters and result |
| --- | --- |
| `a8_version()` | Returns a library-owned NUL-terminated version string. |
| `a8_default_options(opt)` | Fills the caller's non-NULL options pointer; returns void. |
| `a8_create(model_dir,opt)` | Package-root UTF-8/filesystem path and initialized options pointer. Returns engine handle or NULL; creation is synchronous. |
| `a8_create_with_runtime(model_dir,opt,runtime,out)` | Checked model creation using the shared Pandora Runtime, or NULL for default. Writes a persistent empty owner slot; returns 0 or A8_ERR_*. Model retains Runtime state. |
| `a8_destroy_owned(out)` | Returns 0 and clears the caller's owner slot on success; repeated empty cleanup succeeds. Backend or memory cleanup failure returns A8_ERR_NPU and retains the slot; read a8_last_error(*out). Rejects inherited PID with A8_ERR_STATE and leaves its slot unchanged. Wait for in-flight calls first. |
| `a8_create_error()` | Library-owned description of the last creation failure on this thread. |
| `a8_destroy(engine)` | Legacy void cleanup; prefer a8_destroy_owned for visible failure status and a retryable owner slot. After successful destruction the handle is invalid; do not double-destroy or race an in-flight call. |
| `a8_get_info(engine,out)` | Fills caller-owned `a8_info`, returns 0 on success. |
| `a8_last_error(engine)` | Library-owned current error string, not a heap allocation for the caller to free. |
| `a8_reset(engine)` | Resets session state, positions, time, token queue and counters. Returns 0; retains hotword configuration but clears its matching history. |
| `a8_feed(engine,pcm,n)` | Pass `n` finite mono float32 samples at 16 kHz. The SDK preserves amplitudes across the finite float32 range and consumes the data before returning. Choose a chunk size that fits C `int`. Returns the number of newly queued tokens, possibly 0. Feeding after finish is a state error. |
| `a8_read_tokens(engine,out,cap)` | Caller array of at least `cap` a8_token structs, with nonnegative capacity. Pops up to cap oldest queued tokens; returns number written. Repeatedly drain until the queue is empty. |
| `a8_token_bytes(engine,id,buf,cap)` | Writes up to cap UTF-8 bytes to caller storage, not NUL-terminated. Returns the full required byte count, which can exceed cap; then allocate a larger buffer and retry. Empty for non-text tokens. Never treat the required size as bytes already written. Characters can span tokens, so preserve/incrementally decode the byte stream. |
| `a8_finish(engine,tail_tokens)` | `-1` default silent tail (14/17 clocks for 160ms / 80ms), or a nonnegative clock count. Returns new token count. Call once per session and drain; no further feed/soft_reset until reset. Drain token bytes before resetting or destroying the handle. |
| `a8_soft_reset(engine,replay_from_s)` | Replay cached rows newer than this session time in seconds, up to replay_max_s. Requires a token and unfinished session; returns new replay token count. Does not reset the audio tower. |
| `a8_eot_probs(engine,out)` | Caller float array `[4][8]`; reads the last token's semantic-VAD class distribution. Enable semantic VAD and query after a token. |
| `a8_get_stats(engine,out)` | Fills caller-owned a8_stats, returns 0. |
| `a8_set_hotwords(engine,tokenizer_path,words_json,top_k,start_boost,continuation_boost)` | After reset, before audio: matching tokenizer file, or NULL/empty to resolve models.json resources.tokenizer ; JSON array of UTF-8 strings (`[]` disables); top_k 0 or1..vocabulary; finite boosts [0,100]. Returns 0. Limits:256 terms,1024 UTF-8 bytes/term,128 tokens/variant,65536 JSON bytes. Configuration survives reset; matching history clears. The bias is a preference, not a spelling guarantee. |

The complete C99 example accepts exactly four positional arguments:
`MODEL_ROOT INPUT.f32 CLOCK_MS zh|en`. It does not parse `--hotword`,
`--tokenizer` or `--realtime`; use `a8_set_hotwords` in your own C caller for
hotword configuration. Input blocks are processed without realtime pacing.
The example prints a `TRANSCRIPT` marker and UTF-8 bytes plus a newline to stdout,
and token IDs and application diagnostics to stderr. Vendor notices may appear
on either stream; use the C token API for programmatic results. Exit status is
0 on success, 2 on argument/input setup errors, 1 on processing/SDK errors,
or 128+signal (130 for SIGINT,143 for SIGTERM) after cooperative cleanup.

### Compatibility

Use the Python package, public headers and native library from the same SDK delivery.
The current SDK supports the `models.json` version 2 layout for both 80ms and 160ms.
Choose a model target matching the board's SoC, QNN runtime and BSP; target resources alone do not establish compatibility with every system.
See [platform and loader requirements](#target-and-linking) and [model setup](MODEL_SETUP.md).

### Request controls

These C ABI functions support the Python task API and explicit request limits.

| Function | Parameters and result |
| --- | --- |
| `a8_begin_request(e, int lang, int64_t max_new_tokens)` | Start a fresh exclusive request. `lang` is `A8_LANG_ZH` or `A8_LANG_EN`. Restore the selected language prefix and clear audio/LM/token/history/progress state without reloading graphs. `0` cap means native continuous policy; positive cap counts emitted tokens including controls. Configure/clear hotwords separately after beginning. Returns status `0` or negative error. |
| `a8_request_state(e)` | Returns `0` running, `1` normal known-EOF/drained completion, `2` generation cap, or negative error. Copy the last error immediately on failure. |
| `a8_finish_audio(e, const float *pcm, int n, int tail_tokens)` | Append final finite model-rate mono PCM and declare EOF before running remaining work/tails. The feed contract also applies here. Set `n` to a nonnegative count and supply a pointer if `n > 0`. Set `tail_tokens` to -1 for the native default. Returns the number of queued tokens or a negative error. Drain with `a8_read_tokens`. This preserves normal completion when the cap equals the precise final workload. |

A failure during final audio processing returns an error and marks the request failed. Tokens queued before that failure remain readable.

After a live `a8_feed` exhausts the cap, state is terminal `2`; do not call native finish again. A new request must begin/reset before more audio. A finite final-audio call returns state `1` if all required clocks finish exactly at the cap, or `2` if the cap blocks required work. No text slicing implements this budget. `a8_reset` restores the currently selected language and the original uncapped legacy session behavior. Language switching changes only existing prefix/cache state, not weights. All calls remain synchronous and must not race destroy. The Python layer additionally reserves one recording and caches its idempotent finish result; raw C finish is still once-only.

### Model package

The SDK resolves common resources and target graphs from models.json version 2. Pass the root containing models.json; see the [model setup](MODEL_SETUP.md) and [package contract](MODEL_PACKAGE.md). Only models.json format_version 2 with matching AIDEM model graphs and ordinary prefix resources is supported.

## Error codes

The header defines these native status codes:

| Code | Meaning | What the caller should do |
| --- | --- | --- |
| `0` (`A8_OK`) | Success | Positive values may also report success for count-returning calls. |
| `-1` (`A8_ERR_ARG`) | Invalid argument | Correct the inputs and retry. |
| `-2` (`A8_ERR_MODEL`) | Missing or inconsistent model resource | Check the model root and selected target. |
| `-3` (`A8_ERR_NPU`) | QNN or LMS backend failure | Read the last error and follow the cleanup guidance above. |
| `-4` (`A8_ERR_FULL`) | KV capacity exhausted with rolling disabled | Drain queued tokens and reset before starting a new session. |
| `-5` (`A8_ERR_STATE`) | Invalid in the current session state | Check the lifecycle and restore a valid call order. |
| `-6` (`A8_ERR_INTERNAL`) | Unexpected native failure | Read the last error before cleanup. |

Python task exceptions have their own categories and retain `native_code` where available;
see [Capabilities and errors](../sdk/PYTHON_API.md#capabilities-and-errors). A native inference failure
requires closing and recreating the Python model; do not assume that a new request recovers it.

## Threads and ownership

### Host process integration

The SDK leaves host signal masks/handlers, stdout/stderr, global vendor logging,
host resource limits unchanged. Vendor notices may appear.
Calls are synchronous; signal delivery to Python may wait for native return.
Use explicit close/destroy after in-flight work finishes. Persistent native owner
slots permit cleanup after an interrupted return handoff. Model/Runtime handles
are process-local; use spawn/exec, and initialize there instead of inheriting an
initialized QNN provider. See [Runtime](../sdk/RUNTIME_API.md).

<a id="complete-c99-transcription-example"></a>

## Example

A complete program is in [examples/c/transcribe_pcm.c](../examples/c/transcribe_pcm.c).

Use the same delivered `sdk/lib/libaudio8_asr.so` as the Python package. Input is
nonempty mono 16 kHz little-endian finite float32 PCM. The example prints real
token IDs to stderr and native UTF-8 transcript bytes to stdout. Pass an optional
final output path to write only the transcript to a file. Token bytes can split
UTF-8 characters, so concatenate before interpreting the final text.
Runtime controls are documented in [Runtime](../sdk/RUNTIME_API.md).

```bash
mkdir -p .c-example
ffmpeg -y -i examples/audio/speech.wav -f f32le -acodec pcm_f32le -ar 16000 -ac 1 .c-example/audio8-input.f32
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -Wall -Wextra -Werror -I sdk/include examples/c/transcribe_pcm.c \
  -L sdk/lib -L"$runtime_dir" -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" \
  -laudio8_asr -Wl,-rpath,"$PWD/sdk/lib" -o .c-example/audio8-c-example
.c-example/audio8-c-example models .c-example/audio8-input.f32 160 en
```

For the optional 80ms run, first follow the [80ms download instructions](MODEL_SETUP.md#80ms), then run:

```bash
.c-example/audio8-c-example models/audio8-80ms .c-example/audio8-input.f32 80 en
```

SIGINT/SIGTERM request early termination. The main thread waits for the current
synchronous call, then releases the engine and Runtime without a normal tail
flush. File/argument/native errors also release acquired owners. Successful EOF
flushes exactly once and drains all remaining output. No second SDK is required.
