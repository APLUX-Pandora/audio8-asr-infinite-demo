# Model setup

## Device requirements

- A compatible Linux device with Aidlux LMS (`sudo lms check` returns true), drivers, DSP firmware and BSP/FastRPC support.
- Python 3.10–3.12 in the Demo environment (see [Install](../README.md#1-install)).
- The SDK includes its QNN runtime libraries. Do not install QNN separately or set QNN paths.

Use Linux AArch64. Install `ffmpeg` for the Web Demo and C example, and `libsndfile1` for file decoding. See [Build and link](C_ABI.md#build-and-link) for the native system libraries.

## Targets

Pick the folder for your device's SoC. The SDK uses the Linux SoC ID to select a matching target.

| SoC | Target folder |
| --- | --- |
| QCS8550 | `qcs8550_qnn248` |
| QCS8625 | `qcs8625_qnn248` |
| QCS8275 / IQ8 | `qcs8275_qnn248` |
| QCS9075 / IQ9 | `qcs9075_qnn248` |

## Download

From the Demo root, in the activated environment, download the shared resources once and then one target. Run `hf auth login` first if the repository is private.

The examples use QCS8550. For another SoC, replace `qcs8550_qnn248` in the second command with that SoC's target from the table.

### 160ms

```bash
hf download APLUX-Pandora/Audio8-ASR-Infinite-160ms --local-dir models --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Audio8-ASR-Infinite-160ms --local-dir models --include "targets/qcs8550_qnn248/*"
```

Start the Web Demo with `A8_CLOCK_MS=160 bash demo/run.sh --models models --port 8765`. The [examples](../examples/README.md) use this profile by default.

### 80ms

Download this profile separately so both can be used in the same checkout.

```bash
hf download APLUX-Pandora/Audio8-ASR-Infinite-80ms --local-dir models/audio8-80ms --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Audio8-ASR-Infinite-80ms --local-dir models/audio8-80ms --include "targets/qcs8550_qnn248/*"
```

Start the Web Demo with `A8_CLOCK_MS=80 bash demo/run.sh --models models/audio8-80ms --port 8765`. To run the Python examples against this profile, set `MODEL_DIR` in the example to `models/audio8-80ms`. Stop the current Web Demo before starting the other profile on the same port.

### Download pattern for another SoC

Replace `<target-folder>` in the second command with your device's target folder from the table. For the 80ms profile, use its repository and local directory shown above.

From the Demo root, in the activated environment, download the shared resources once and then one target:

```bash
hf download APLUX-Pandora/Audio8-ASR-Infinite-160ms --local-dir models --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Audio8-ASR-Infinite-160ms --local-dir models --include "targets/<target-folder>/*"
```

Run `hf auth login` first if the repository is private. Keep one target per model folder: to switch devices, move the old `targets/` folder out or download into a new folder.

### Integrity and compatibility

Set `MODEL_DIR` to the downloaded profile folder and `TARGET` to the selected target from the table before running this optional check.

The root checksum list verifies `models.json`, its required common resources, and the selected target's checksum list. The target list must cover all four declared graphs and every graph must match. Other targets and presentation media are not needed for this check.

```bash
python - "$MODEL_DIR" "$TARGET" <<'PY'
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
if not re.fullmatch(r'[a-z0-9_]+', sys.argv[2]):
    sys.exit('Set TARGET to a name from the supported targets table.')
target_dir = Path('targets') / sys.argv[2]


def verify(directory, names, *, exact=False):
    rows = {}
    for line in (directory / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64}) [ *](.+)', line)
        if match is None or match[2] in rows:
            sys.exit(f'Invalid checksum list: {directory / "SHA256SUMS"}')
        rows[match[2]] = line
    if names - rows.keys() or (exact and rows.keys() - names):
        sys.exit(f'Checksum list does not cover the expected files: {directory / "SHA256SUMS"}')
    for name in names:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not (directory / path).resolve().is_relative_to(directory):
            sys.exit(f'Invalid model resource path: {name}')
    subprocess.run(['sha256sum', '--strict', '--check', '-'], cwd=directory,
                   input='\n'.join(rows[name] for name in sorted(names)) + '\n',
                   text=True, check=True)


manifest = json.loads((root / 'models.json').read_text(encoding='utf-8'))
if manifest['format_version'] != 2:
    sys.exit('Unsupported models.json format.')
selected = [target for target in manifest['targets'] if target['directory'] == target_dir.as_posix()]
if len(selected) != 1:
    sys.exit(f'Target is missing or duplicated in models.json: {target_dir}')
files = selected[0]['files']
graphs = {Path(files[role]).relative_to(target_dir).as_posix()
          for role in ('encoder', 'adapter', 'decoder_1', 'decoder_2')}
if len(graphs) != 4:
    sys.exit(f'Expected four distinct graph files in {target_dir}.')

resources = manifest['resources']
common = {resources[key] for key in ('frontend_config', 'audio_constants', 'mel_filters',
                                     'vocabulary', 'tokenizer', 'rotation')}
common.add(resources['token_vectors']['path'])
common.update(resources['prefix'][key] for key in ('encoder', 'decoder_zh', 'decoder_en'))
common.update(resources['semantic_vad'][key] for key in ('weight', 'bias', 'config'))
verify(root, common | {'models.json', (target_dir / 'SHA256SUMS').as_posix()})
verify(root / target_dir, graphs, exact=True)
PY
```

Continue only if both checksum checks succeed. If a check fails, repeat the downloads for this model and selected target, then run the same command again.

## Folder layout

After the download, `models/` looks like this:

```text
models/
├── models.json
├── SHA256SUMS
├── frontend/
├── prefix/
├── semantic_vad/
├── targets/qcs8550_qnn248/
│   ├── SHA256SUMS
│   └── *.bin.aidem
└── audio8-80ms/  (optional; same layout)
```

The SDK reads `models.json`, checks that the shared resources and one complete target are present, and reports what is missing. `hf download` verifies each large file's checksum.

The SDK selects the target for the local SoC. QCS8275 also accepts the QCS8625 target when its own target is missing. If no compatible target is available, the error shows the detected SoC and the complete targets found. Pass the folder containing `models.json` to the SDK. See [Model package](MODEL_PACKAGE.md) for resource details.

## Troubleshooting

| Message or symptom | What to do |
| --- | --- |
| `models.json is required` | Pass the model folder containing `models.json` and complete the shared download if it is missing. |
| No complete model target for local SoC | Download the row for the SoC shown in the error. |
| LMS activation check fails | Activate LMS on the device and rerun the check in [Install](../README.md#1-install). |
| Port already in use | Stop the running Web Demo or choose another port. |
