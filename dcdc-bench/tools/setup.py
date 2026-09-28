"""Create a local development environment and install pinned document tools.

Run from any directory: python tools/setup.py. Nothing connects to hardware.
Linux system browser libraries must already be installed (see README).
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import venv
import zipfile

QUARTO = "1.10.18"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or later is required")
    destination = ROOT / ".venv"
    venv.EnvBuilder(with_pip=True).create(destination)
    python = destination / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "-e", str(ROOT)+"[report,test]"], check=True)
    tools = ROOT / ".tools"
    tools.mkdir(exist_ok=True)
    system, machine = platform.system(), platform.machine().lower()
    suffix = {("Linux", "aarch64"): "linux-arm64.tar.gz", ("Linux", "arm64"): "linux-arm64.tar.gz",
              ("Linux", "x86_64"): "linux-amd64.tar.gz", ("Windows", "amd64"): "win.zip"}.get((system,machine))
    if suffix is None:
        raise SystemExit("Install Quarto 1.10.18 from quarto.org and set QUARTO_PATH; this setup targets Windows x64 and Linux x64/ARM64")
    url = f"https://api.github.com/repos/quarto-dev/quarto-cli/releases/tags/v{QUARTO}"
    with urllib.request.urlopen(url, timeout=60) as response:
        release = json.load(response)
    asset = next(item for item in release["assets"] if item["name"].endswith(suffix))
    digest = asset.get("digest", "")
    if not digest.startswith("sha256:"):
        raise SystemExit("Official release checksum unavailable; install the renderer manually")
    archive = tools / asset["name"]
    with urllib.request.urlopen(asset["browser_download_url"], timeout=120) as source, archive.open("wb") as target:
        shutil.copyfileobj(source, target)
    with archive.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != digest.split(":",1)[1]:
            raise SystemExit("Quarto checksum mismatch")
    if suffix.endswith(".gz"):
        with tarfile.open(archive) as source:
            source.extractall(tools, filter="data")
    else:
        with zipfile.ZipFile(archive) as source:
            if any(Path(name).is_absolute() or ".." in Path(name).parts for name in source.namelist()):
                raise SystemExit("Unsafe archive path")
            source.extractall(tools / f"quarto-{QUARTO}")
    archive.unlink()
    if not any(shutil.which(name) for name in ("chromium-headless-shell", "chromium", "google-chrome")):
        # Playwright downloads its tested local browser; no control server starts.
        subprocess.run([str(python), "-m", "playwright", "install", "chromium"], check=True)
        script = "from playwright.sync_api import sync_playwright\nwith sync_playwright() as p: print(p.chromium.executable_path)"
        browser = subprocess.check_output([str(python), "-c", script], text=True).strip()
        (tools / "browser-path.txt").write_text(browser)
    print(f"Environment ready. Run {python} -m dcdc_bench demo --out {ROOT / 'examples/generated'}")


if __name__ == "__main__":
    main()
