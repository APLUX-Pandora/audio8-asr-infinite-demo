"""Validate the native files selected for SDK packaging."""
import json
from pathlib import Path
import re
import shutil

_RUNTIME_METADATA = frozenset(Path(name) for name in (
    "inventory.json", "manifest.json", "LICENSE.pdf", "NOTICE.txt", "QNN_NOTICE.txt", "QNN_README.txt", "sdk.yaml",
))
_SHARED_LIBRARY = re.compile(r"\.so(?:\.|$)")
NATIVE_LICENSES = (
    "LICENSE", "LICENSE.zh-CN.txt", "THIRD_PARTY_NOTICES.txt",
    "LICENSES/Apache-2.0.txt", "LICENSES/ICU.txt", "LICENSES/OpenSSL-copyright.txt",
    "LICENSES/Pandora-QNN-Runtime-Apache-2.0.txt", "LICENSES/Pandora-QNN-Runtime-NOTICE.txt",
    "LICENSES/Silero-VAD-MIT.txt",
)


def check_native_licenses(lib):
    missing = [name for name in NATIVE_LICENSES if not (lib / name).is_file()]
    if missing:
        raise ValueError("Missing required native SDK licenses/notices: " + ", ".join(missing))


def copy_native_licenses(source, destination):
    for name in NATIVE_LICENSES:
        output = destination / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, output)


def runtime_payload(runtime):
    if runtime.is_symlink():
        raise ValueError("QNN runtime must not be a symlink")
    inventory = json.loads((runtime / "inventory.json").read_text())
    manifest = json.loads((runtime / "manifest.json").read_text())
    version = inventory["qnn"]
    source = f"Qualcomm QNN SDK {version}"
    if inventory.get("source") != source or manifest.get("source") != source or manifest["qnn_version"] != version:
        raise ValueError("QNN metadata must identify the same vendor SDK release")
    entries = inventory["files"]
    expected = set(_RUNTIME_METADATA)
    for row in entries:
        source_path = Path(row["source"])
        if source_path.is_absolute() or ".." in source_path.parts:
            raise ValueError("QNN inventory source must be relative to the vendor SDK")
        relative = Path(row["path"])
        if (relative.is_absolute() or ".." in relative.parts or relative in expected
                or not _SHARED_LIBRARY.search(relative.name)):
            raise ValueError("Invalid QNN inventory path: " + row["path"])
        expected.add(relative)
    paths = list(runtime.rglob("*"))
    actual = {path.relative_to(runtime) for path in paths if path.is_file() or path.is_symlink()}
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    symlinks = sorted(path.relative_to(runtime) for path in paths if path.is_symlink())
    if missing or unexpected or symlinks:
        raise ValueError(f"QNN runtime differs from inventory: missing={missing}, extra={unexpected}, symlinks={symlinks}")
    return expected, entries


def check_shared_libraries(paths, allowed):
    extra = sorted(path for path in paths if _SHARED_LIBRARY.search(path.name) and path not in allowed)
    if extra:
        raise ValueError("Shared libraries outside the SDK inventory: " + ", ".join(map(str, extra)))
