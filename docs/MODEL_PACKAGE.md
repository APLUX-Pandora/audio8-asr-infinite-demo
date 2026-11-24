# Configurable models.json package

The root models.json is the interface between HF resources and the native/Python SDK. Version2 declares all paths; no resource registry of implicit filenames or per-target target.json is required.

```json
{
  "format_version": 2,
  "model_name": "Audio8-ASR-Infinite-160ms",
  "audio_clock_ms": 160,
  "targets": [
    {
      "soc": "qcs8550",
      "qnn_version": "2.48",
      "directory": "targets/qcs8550_qnn248",
      "files": {
        "encoder": "targets/qcs8550_qnn248/encoder.bin.aidem",
        "adapter": "targets/qcs8550_qnn248/adapter.bin.aidem",
        "decoder_1": "targets/qcs8550_qnn248/decoder_1.bin.aidem",
        "decoder_2": "targets/qcs8550_qnn248/decoder_2.bin.aidem"
      }
    }
  ],
  "resources": {
    "frontend_config": "frontend/config.json",
    "audio_constants": "frontend/rows_const.npy",
    "mel_filters": "mel_filters.npy",
    "vocabulary": "token_bytes.json",
    "tokenizer": "tokenizer.json",
    "rotation": "rotation.npy",
    "token_vectors": {
      "path": "embedding.bin",
      "dtype": "float32-le",
      "shape": [
        151936,
        2048
      ],
      "layout": "row-major"
    },
    "prefix": {
      "encoder": "prefix/encoder.bin",
      "decoder_zh": "prefix/decoder_zh.bin",
      "decoder_en": "prefix/decoder_en.bin"
    },
    "semantic_vad": {
      "weight": "semantic_vad/weight.npy",
      "bias": "semantic_vad/bias.npy",
      "config": "semantic_vad/config.json"
    }
  }
}
```

All paths are relative to the model-package root, including target graph paths. Resource keys express semantic purposes rather than filenames. Ordinary resources use strings; token_vectors additionally declares its raw binary representation. Hashes are maintained exclusively in SHA256SUMS. Target directory is an explicitly configured grouping used for selective download/completeness; graphs must remain within that directory. Renaming common files, graph files or the target directory only requires updating configuration and checksums.

The SDK reads the local SoC ID and selects the complete target for that device. QCS8275 prefers its own target and can also use QCS8625 files. If the required target is missing or incomplete, the error lists the local device and the complete targets found. The SDK checks file presence, sizes and declared paths, then decrypts and loads the graphs. The download checksums can be checked separately.

The native SDK, Python package and Web preflight use this package contract. Public model_files(model_dir, clock_ms) supplies resolved runtime paths to application preflight without implementing inference. The SDK requires models.json format_version 2 with matching AIDEM model graphs and ordinary prefix resources. manifest.json and models.json format_version 1 are not supported.

Embedding shape dimensions must be JSON integers with the exact supported values [151936, 2048]. Floating-point spellings (including 151936.0), booleans, strings, out-of-range dimensions and malformed arrays are rejected before native allocation. The Python and native loaders enforce the same rule.
