"""Package the matched prebuilt native library; do not compile the engine during installation."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist
from setuptools.errors import SetupError
from wheel.bdist_wheel import bdist_wheel

ROOT = Path(__file__).resolve().parent
# PEP 517 may execute this script without adding the source directory to sys.path.
sys.path.insert(0, str(ROOT))
from _build_payload import check_native_licenses, check_shared_libraries, copy_native_licenses, runtime_payload


def check_release_version(version):
    header = (ROOT / "include/audio8_asr.h").read_text(encoding="utf-8")
    match = re.search(r'^#define A8_VERSION "([0-9]+\.[0-9]+\.[0-9]+)"$', header, re.MULTILINE)
    release = ROOT.parent / "VERSION"
    if not match or match[1] != version or (release.is_file() and release.read_text().strip() != version):
        raise SetupError("Python package version must match the SDK release version")


def checked_runtime(library):
    check_native_licenses(ROOT / "lib")
    runtime = ROOT / "lib/qnn248"
    files, entries = runtime_payload(runtime)
    allowed = {library, *(runtime / name for name in files)}
    check_shared_libraries((ROOT / "lib").rglob("*"), allowed)
    return files, entries


class SourceSDK(sdist):
    def run(self):
        check_release_version(self.distribution.get_version())
        pairing = json.loads((ROOT / "native-library.json").read_text())
        checked_runtime(ROOT / "lib" / pairing["filename"])
        super().run()


class BuildSDK(build_py):
    def run(self):
        check_release_version(self.distribution.get_version())
        pairing = json.loads((ROOT / "native-library.json").read_text())
        library = ROOT / "lib" / pairing["filename"]
        if not library.is_file():
            raise SetupError("Missing lib/libaudio8_asr.so: obtain the matching prebuilt SDK Release before installing")
        payload = library.read_bytes()
        if payload[:4] != b"\x7fELF" or int.from_bytes(payload[18:20], "little") != 183:
            raise SetupError("The packaged native library must be an AArch64 ELF")
        if hashlib.sha256(payload).hexdigest() != pairing["sha256"]:
            raise SetupError("Native library SHA256 does not match native-library.json; use the matched release")
        runtime = ROOT / "lib/qnn248"
        files, entries = checked_runtime(library)
        for row in entries:
            component = runtime / row["path"]
            if component.stat().st_size != row["bytes"] or hashlib.sha256(component.read_bytes()).hexdigest() != row["sha256"]:
                raise SetupError("Packaged QNN component mismatch: " + row["path"])
        target = Path(self.build_lib) / "pandora_audio8_asr_infinite" / "lib"
        # Setuptools can reuse a build tree from before the shared Runtime migration.
        (target.parent / "runtime.py").unlink(missing_ok=True)
        super().run()
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(library, target / library.name)
        staged_runtime = target / "qnn248"
        allowed = {target / library.name, *(staged_runtime / name for name in files)}
        check_shared_libraries(target.parent.rglob("*"), allowed)
        for name in sorted(files):
            output = staged_runtime / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(runtime / name, output)
        copy_native_licenses(ROOT / "lib", target)
        shutil.copy2(ROOT / "native-library.json", Path(self.build_lib) / "pandora_audio8_asr_infinite" / "native-library.json")


class LinuxAArch64Wheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False
        self.plat_name = "linux_aarch64"

    def get_tag(self):
        # ctypes uses a C ABI, not a CPython extension ABI. The payload is still platform-specific.
        return "py3", "none", "linux_aarch64"


setup(cmdclass={"build_py": BuildSDK, "bdist_wheel": LinuxAArch64Wheel, "sdist": SourceSDK})
