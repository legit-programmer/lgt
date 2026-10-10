"""Prepare a native, relocatable Python backend for the Tauri release bundle.

Run through `pnpm bundle` from desktop/. uv is only required on the build
machine. The installed desktop application uses this real interpreter rather
than a frozen executable, preserving subprocesses that relaunch sys.executable.
Each OS/architecture must build its own bundle; cross-compiling is unsupported.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "desktop" / "src-tauri" / "resources"
DESTINATION = RESOURCES / "backend"


def run(*arguments: str | Path, capture: bool = False) -> str:
    completed = subprocess.run(
        [str(argument) for argument in arguments],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return (completed.stdout or "").strip()


def safe_remove(path: Path) -> None:
    """Restrict recursive cleanup to generated backend folders in resources."""
    resolved = path.resolve()
    resources = RESOURCES.resolve()
    if resolved.parent != resources or not (
        resolved.name == "backend" or resolved.name.startswith(".backend-")
    ):
        raise RuntimeError(f"Refusing to remove unexpected build path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(f"{platform.system()}:{platform.machine()}:python3.13".encode())
    paths = [ROOT / "uv.lock", ROOT / "pyproject.toml", Path(__file__)]
    paths.append(ROOT / "scripts" / "check-backend-runtime.py")
    paths.extend(sorted((ROOT / "lgt").rglob("*.py")))
    paths.append(ROOT / "lgt" / "schema.sql")
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> None:
    RESOURCES.mkdir(parents=True, exist_ok=True)
    identity = fingerprint()
    manifest = DESTINATION / "lgt-build.json"
    python_relative = Path("python.exe") if os.name == "nt" else Path("bin/python3")
    if manifest.is_file() and (DESTINATION / python_relative).is_file():
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        if previous.get("fingerprint") == identity:
            print("Bundled Lgt backend is up to date.")
            return

    # --system prevents choosing the active project venv. Only uv-managed
    # python-build-standalone distributions are portable enough to copy.
    run("uv", "python", "install", "3.13")
    source_python = Path(run(
        "uv", "python", "find", "--system", "--managed-python", "3.13", capture=True
    ))
    source = Path(run(source_python, "-c", "import sys; print(sys.base_prefix)", capture=True))
    if (source / "pyvenv.cfg").exists():
        raise RuntimeError("The backend bundle requires a standalone Python, not a virtual environment")

    staging = Path(tempfile.mkdtemp(prefix=".backend-", dir=RESOURCES))
    try:
        shutil.copytree(
            source, staging, dirs_exist_ok=True, symlinks=os.name != "nt",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        python = staging / python_relative
        if not python.is_file():
            raise RuntimeError(f"Standalone runtime is missing {python_relative}")
        requirements = staging / "lgt-requirements.txt"
        run("uv", "export", "--quiet", "--frozen", "--no-dev", "--no-emit-project",
            "--no-hashes", "--output-file", requirements)
        # This modifies only our staging copy, never uv's managed installation.
        run("uv", "pip", "install", "--break-system-packages", "--python", python,
            "--requirements", requirements)
        site_packages = Path(run(
            python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))", capture=True
        ))
        if not site_packages.resolve().is_relative_to(staging.resolve()):
            raise RuntimeError("Copied interpreter is not relocatable: site-packages escaped the bundle")
        shutil.copytree(
            ROOT / "lgt", site_packages / "lgt",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        # These imports validate native extensions and the real-interpreter
        # modules used by both CLI process hosting paths; no model calls.
        run(python, "-c", "import fastapi, uvicorn, PIL, openai_codex, lgt.processes, lgt.sdk_host")
        requirements.unlink()
        (staging / "lgt-build.json").write_text(json.dumps({
            "fingerprint": identity,
            "platform": platform.system(),
            "architecture": platform.machine(),
            "python": run(python, "--version", capture=True),
        }, indent=2), encoding="utf-8")
        safe_remove(DESTINATION)
        staging.rename(DESTINATION)
        # Validate again after relocation. Both the Python executable and
        # package data must work outside the build staging directory.
        run(DESTINATION / python_relative, "-m", "lgt", "--help")
        run(DESTINATION / python_relative, ROOT / "scripts" / "check-backend-runtime.py")
        print(f"Prepared native backend runtime: {DESTINATION}")
    finally:
        safe_remove(staging)


if __name__ == "__main__":
    main()
