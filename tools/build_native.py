"""Build the native core (native/wfcore) and install it next to the engine.

    python tools/build_native.py [--debug]

Needs a Rust toolchain (cargo). The engine runs without the library (pure
Python reference); with it, hot paths run natively with identical results.
"""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "native" / "wfcore"
TARGET = ROOT / "vendor" / "wfarsenal" / ("wfcore.pyd" if os.name == "nt" else "wfcore.so")


def main() -> int:
    profile = "debug" if "--debug" in sys.argv else "release"
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
    command = [cargo, "build"] + ([] if profile == "debug" else ["--release"])
    env = dict(
        os.environ,
        CARGO_BUILD_JOBS=os.environ.get("CARGO_BUILD_JOBS", "14"),
        PYO3_PYTHON=os.environ.get("PYO3_PYTHON", sys.executable),
    )
    if profile == "release" and "RUSTFLAGS" not in env and platform.machine().lower() in ("amd64", "x86_64"):
        env["RUSTFLAGS"] = "-C target-cpu=x86-64-v3"
    # Cargo reports progress on stderr; pass it on as stdout so a caller that
    # treats native stderr as an error (build-portable.ps1 under
    # $ErrorActionPreference = "Stop" with redirected output) does not abort.
    build = subprocess.run(command, cwd=CRATE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", errors="replace", env=env)
    print(build.stdout, end="")
    if build.returncode:
        return build.returncode
    built = CRATE / "target" / profile / ("wfcore.dll" if os.name == "nt" else "libwfcore.so")
    try:
        shutil.copyfile(built, TARGET)
    except PermissionError:
        # Windows keeps a loaded library locked; it can still be renamed, so
        # running processes keep the old copy and new ones load the new one.
        for stale in TARGET.parent.glob(TARGET.name + ".old-*"):
            try:
                stale.unlink()
            except OSError:
                pass
        TARGET.rename(TARGET.with_name(f"{TARGET.name}.old-{os.getpid()}"))
        shutil.copyfile(built, TARGET)
    print(f"installed {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
