# -*- mode: python ; coding: utf-8 -*-
# Сборка одного exe: pyinstaller --noconfirm --clean SdelkiAmoCRM.spec
from PyInstaller.utils.hooks import collect_data_files

datas = [("static", "static"), ("config.json", ".")]
# драйвер Playwright (node.exe + js) — без него бот не сможет управлять браузером
datas += collect_data_files("playwright")

a = Analysis(
    ["app.py"],
    datas=datas,
    hiddenimports=["make_shortcut"],
    excludes=["tkinter", "PIL", "numpy"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="SdelkiAmoCRM",
    icon="assets/icon.ico",
    console=False,        # без чёрного окна; программа сама закрывается, когда закрыто её окно
    upx=False,
    version=None,
)
