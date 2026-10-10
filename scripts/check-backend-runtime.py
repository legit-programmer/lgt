"""Verify the packaged interpreter, process hosts and daemon without model calls."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


async def check_process_host() -> None:
    from lgt.codex_adapter import bundled_codex_binary
    from lgt.processes import spawn_command

    tree = await spawn_command(
        [sys.executable, "-c", "print('lgt-process-host-ok')"],
        os.getcwd(), line_limit=1048576,
    )
    try:
        stdout, stderr = await asyncio.wait_for(tree.process.communicate(), timeout=15)
        assert tree.process.returncode == 0, stderr.decode()
        assert stdout.strip() == b"lgt-process-host-ok", stdout
    finally:
        await tree.close()
    binary = Path(bundled_codex_binary())
    assert binary.is_file(), binary
    completed = subprocess.run([str(binary), "--version"], capture_output=True, check=True, timeout=15)
    assert b"codex" in completed.stdout.lower(), completed.stdout


def request(port: int, token: str | None = None, method: str = "GET") -> dict:
    route = "shutdown" if method == "POST" else "health"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    call = urllib.request.Request(f"http://127.0.0.1:{port}/{route}", headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(call, timeout=3) as response:
        return json.load(response)


def check_daemon() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="lgt-bundle-smoke-") as directory:
        temporary = Path(directory)
        config = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
        config["settings"]["data_dir"] = str(temporary / "data")
        # No live CLI discovery or credentials are needed for this protocol test.
        missing = str(temporary / "missing-harness")
        config.update(codex_bin=missing, claude_command=[missing], gemini_command=[missing])
        config_path = temporary / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with (temporary / "launch.log").open("wb") as log:
            daemon = subprocess.Popen(
                [sys.executable, "-m", "lgt", "--config", str(config_path), "--port", "0", "--daemon"],
                cwd=temporary, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            descriptor_path = temporary / "data" / "daemon.json"
            try:
                deadline = time.monotonic() + 30
                while not descriptor_path.exists():
                    if daemon.poll() is not None:
                        raise AssertionError((temporary / "launch.log").read_text())
                    if time.monotonic() > deadline:
                        raise TimeoutError("Bundled daemon did not publish its descriptor")
                    time.sleep(0.1)
                descriptor = json.loads(descriptor_path.read_text())
                health = request(descriptor["port"], descriptor["token"])
                assert health["application"] == "lgt" and health["api_version"] == 1, health
                assert health["pid"] == descriptor["pid"], health
                assert request(descriptor["port"], descriptor["token"])["pid"] == health["pid"]
                try:
                    request(descriptor["port"])
                except urllib.error.HTTPError as error:
                    assert error.code == 401, error
                else:
                    raise AssertionError("Daemon health accepted a missing launch token")
                request(descriptor["port"], descriptor["token"], "POST")
                daemon.wait(timeout=20)
                assert daemon.returncode == 0, daemon.returncode
                assert not descriptor_path.exists(), "Daemon descriptor survived shutdown"
            finally:
                if daemon.poll() is None:
                    daemon.terminate()
                    daemon.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true", help="Also verify authenticated startup and shutdown")
    arguments = parser.parse_args()
    asyncio.run(check_process_host())
    if arguments.daemon:
        check_daemon()
    print("Bundled interpreter, child process host and Codex binary verified.")
