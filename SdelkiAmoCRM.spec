# -*- mode: python ; coding: utf-8 -*-
# Сборка программы папкой: dist/SdelkiAmoCRM/ (SdelkiAmoCRM.exe + _internal).
# Из папки Inno Setup делает один установщик (installer.iss).
#
# Почему не один exe (onefile): такой exe при запуске распаковывает себя во временную
# папку и запускает оттуда — Защитник Windows принимает это за вирус (Wacatac.B!ml).
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                 StringTable, VarFileInfo, VarStruct, VSVersionInfo)

VERSION = re.search(r'VERSION = "(.+?)"', Path("paths.py").read_text(encoding="utf-8")).group(1)
nums = tuple(int(x) for x in VERSION.split(".")) + (0,) * (4 - len(VERSION.split(".")))

# сведения о программе в свойствах exe — антивирусы доверяют таким файлам больше
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums),
    kids=[
        StringFileInfo([StringTable("041904B0", [
            StringStruct("CompanyName", "YourDax"),
            StringStruct("FileDescription", "Сделки amoCRM — создание сделок из отчёта"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "SdelkiAmoCRM"),
            StringStruct("OriginalFilename", "SdelkiAmoCRM.exe"),
            StringStruct("ProductName", "Сделки amoCRM"),
            StringStruct("ProductVersion", VERSION),
            StringStruct("LegalCopyright", "YourDax"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0419, 1200])]),
    ],
)

datas = [("static", "static"), ("config.json", ".")]
# драйвер Playwright (node.exe + js) — без него бот не сможет управлять браузером
datas += collect_data_files("playwright")

a = Analysis(
    ["app.py"],
    datas=datas,
    excludes=["tkinter", "PIL", "numpy"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SdelkiAmoCRM",
    icon="assets/icon.ico",
    console=False,        # без чёрного окна; программа сама закрывается, когда закрыто её окно
    upx=False,
    version=version_info,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SdelkiAmoCRM", upx=False)
