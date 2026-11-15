"""Ярлык «Сделки amoCRM» на рабочем столе.

* из исходников (`python make_shortcut.py`) — на run.bat;
* из exe — на сам exe (вызывается автоматически при первом запуске).
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "Сделки amoCRM"


def create(target: Path) -> bool:
    target = Path(target).resolve()
    icon = f"{target},0" if target.suffix.lower() == ".exe" else r"$env:SystemRoot\System32\imageres.dll,109"
    style = 1 if target.suffix.lower() == ".exe" else 7  # run.bat — свёрнутой консолью
    ps = f"""
$desk = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut((Join-Path $desk '{NAME}.lnk'))
$lnk.TargetPath = '{target}'
$lnk.WorkingDirectory = '{target.parent}'
$lnk.WindowStyle = {style}
$lnk.IconLocation = "{icon}"
$lnk.Description = 'Создание сделок в amoCRM из отчёта'
$lnk.Save()
"""
    # -EncodedCommand (UTF-16LE) — чтобы кириллица в пути и имени не ломалась
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc],
                       capture_output=True, creationflags=flags)
    return r.returncode == 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ok = create(ROOT / "run.bat")
    print("Ярлык на рабочем столе создан." if ok else "Не удалось создать ярлык.")


if __name__ == "__main__":
    main()
