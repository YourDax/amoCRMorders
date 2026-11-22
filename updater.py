"""Install and start GitHub releases alongside the last working build."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

APP_EXE = "SdelkiAmoCRM.exe"
UPDATE_ASSET = "SdelkiAmoCRM-update.zip"
RELEASE_API = "https://api.github.com/repos/YourDax/amoCRMorders/releases/latest"
RELEASE_DOWNLOAD = "https://github.com/YourDax/amoCRMorders/releases/download/"
READY_ENV = "SDELKI_UPDATE_READY"
VERSION_PATTERN = re.compile(r"[0-9]{1,5}(?:\.[0-9]{1,5}){2}")
MAX_DOWNLOAD = 1024 * 1024 * 1024


def version_parts(version):
    if isinstance(version, str) and VERSION_PATTERN.fullmatch(version):
        return tuple(map(int, version.split(".")))
    return ()


def select_asset(release, current):
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        return None
    version = tag[1:]
    if version_parts(version) <= version_parts(current):
        return None
    if release.get("prerelease") or release.get("draft"):
        return None
    for asset in release.get("assets", []):
        if asset.get("name") != UPDATE_ASSET:
            continue
        if asset.get("browser_download_url") != f"{RELEASE_DOWNLOAD}{tag}/{UPDATE_ASSET}":
            continue
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", asset.get("digest") or ""):
            continue
        size = asset.get("size")
        if isinstance(size, int) and 0 < size <= MAX_DOWNLOAD:
            return version, asset
    return None


def fetch(url):
    return urlopen(Request(url, headers={"User-Agent": "SdelkiAmoCRM-updater"}), timeout=5)


def download(asset, archive):
    digest = hashlib.sha256()
    remaining = asset["size"]
    deadline = time.monotonic() + 180
    with fetch(asset["browser_download_url"]) as response, archive.open("wb") as output:
        while chunk := response.read1(1024 * 1024):
            remaining -= len(chunk)
            if remaining < 0 or time.monotonic() > deadline:
                raise OSError("Update download exceeded its size or time limit")
            digest.update(chunk)
            output.write(chunk)
    if remaining or "sha256:" + digest.hexdigest() != asset["digest"]:
        raise OSError("Update download failed integrity verification")


def stage_release(root, current):
    with fetch(RELEASE_API) as response:
        selected = select_asset(json.loads(response.read(1024 * 1024)), current)
    if selected is None:
        return None
    version, asset = selected
    target = root / version
    if (root / f"{version}.failed").exists():
        return None
    if (target / APP_EXE).is_file():
        return target

    with tempfile.TemporaryDirectory(prefix="download-", dir=root) as directory:
        temporary = Path(directory)
        archive = temporary / UPDATE_ASSET
        download(asset, archive)
        staging = temporary / "app"
        with ZipFile(archive) as package:
            package.extractall(staging)
        if not (staging / APP_EXE).is_file() or not (staging / "_internal").is_dir():
            raise OSError("Update archive does not contain the application")
        staging.rename(target)
    return target


def start_and_wait(build, args):
    executable = build / APP_EXE
    if not executable.is_file():
        return False

    with tempfile.TemporaryDirectory(prefix="launch-", dir=build.parent) as directory:
        ready = Path(directory) / "ready"
        environment = {
            **os.environ,
            READY_ENV: str(ready),
            "PYINSTALLER_RESET_ENVIRONMENT": "1",
        }
        process = subprocess.Popen([str(executable), *args], env=environment)
        deadline = time.monotonic() + 25
        started = False
        try:
            while process.poll() is None and time.monotonic() < deadline:
                if ready.is_file():
                    started = True
                    return True
                time.sleep(0.1)
        finally:
            if not started and process.poll() is None:
                process.kill()
                process.wait()
    return False


def try_build(build, args):
    try:
        return start_and_wait(build, args)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Не удалось запустить {build.name}: {error}")
        return False


def remove_cached_build(build):
    try:
        if build.is_dir() and build.resolve() == build.parent.resolve() / build.name:
            shutil.rmtree(build)
    except OSError as error:
        print(f"Не удалось убрать файлы версии {build.name}: {error}")


def select_version(root, installed, args):
    current = root / "current"
    try:
        previous = current.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        previous = ""
    if version_parts(previous) <= version_parts(installed):
        previous = installed

    try:
        candidate = stage_release(root, previous)
    except Exception as error:
        print(f"Обновление пропущено: {error}")
        candidate = None

    if candidate is not None:
        if try_build(candidate, args):
            try:
                temporary = root / "current.tmp"
                temporary.write_text(candidate.name, encoding="ascii")
                temporary.replace(current)
            except OSError as error:
                print(f"Не удалось сохранить текущую версию: {error}")
            else:
                for cached in root.glob("*"):
                    if version_parts(cached.name) and cached.name not in {candidate.name, previous}:
                        remove_cached_build(cached)
            return True
        try:
            (root / f"{candidate.name}.failed").touch()
        except OSError as error:
            print(f"Не удалось сохранить результат обновления: {error}")
        remove_cached_build(candidate)

    return previous != installed and try_build(root / previous, args)


@contextmanager
def startup_lock(root):
    """Keep other launches out until this launch has bound the application port."""
    import msvcrt

    try:
        root.mkdir(parents=True, exist_ok=True)
        lock = (root / "startup.lock").open("a+b")
    except OSError as error:
        print(f"Не удалось проверить обновление: {error}")
        yield None
        return
    with lock:
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except PermissionError:
            yield False
        else:
            yield True
