"""Положение окон Edge и Chromium в рабочей области монитора Windows."""

from __future__ import annotations

import ctypes
import re
import subprocess
import sys
import time
from ctypes import wintypes


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32")
    _dwmapi = ctypes.WinDLL("dwmapi")
    _enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.EnumWindows.argtypes = [_enum_callback, wintypes.LPARAM]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsZoomed.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.MonitorFromWindow.restype = wintypes.HANDLE
    _user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _set_thread_dpi = getattr(_user32, "SetThreadDpiAwarenessContext", None)
    if _set_thread_dpi:
        _set_thread_dpi.argtypes = [ctypes.c_void_p]
        _set_thread_dpi.restype = ctypes.c_void_p
    _dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                              ctypes.c_void_p, wintypes.DWORD]
else:
    _user32 = None


def foreground_window():
    return _user32.GetForegroundWindow() if _user32 else None


def find_browser_pids(profile) -> list[int]:
    """Главные процессы Edge/Chromium, запущенные с указанным профилем."""
    if not _user32:
        return []
    command = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\' OR Name=\'chrome.exe\'" | '
        'ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }'
    )
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    profile_arg = re.compile(r'--user-data-dir="?' + re.escape(str(profile)) + r'(?=["\s]|$)', re.I)
    pids = []
    for line in result.stdout.splitlines():
        pid, _, command_line = line.partition("\t")
        if pid.strip().isdigit() and "--type=" not in command_line and profile_arg.search(command_line):
            pids.append(int(pid))
    return pids


def _wait_for_window(pids: set[int], seconds: float):
    if not pids:
        return None
    window = None
    title_class = ctypes.create_unicode_buffer(64)
    pid = wintypes.DWORD()

    @_enum_callback
    def visit(hwnd, _):
        nonlocal window
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and _user32.IsWindowVisible(hwnd):
            length = _user32.GetClassNameW(hwnd, title_class, len(title_class))
            if length and title_class.value == "Chrome_WidgetWin_1":
                window = hwnd
                return False
        return True

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _user32.EnumWindows(visit, 0)
        if window:
            return window
        time.sleep(0.1)
    return None


def _half(work: wintypes.RECT, right: bool) -> tuple[int, int, int, int]:
    middle = work.left + (work.right - work.left) // 2
    left, end = (middle, work.right) if right else (work.left, middle)
    return left, work.top, end, work.bottom


def _place(window, reference, right: bool):
    # Один поток временно работает с физическими пикселями обоих мониторов.
    previous = _set_thread_dpi(ctypes.c_void_p(-4)) if _set_thread_dpi else None  # per-monitor v2
    try:
        anchor = reference if reference and _user32.IsWindow(reference) else window
        monitor = _user32.MonitorFromWindow(anchor, 2)  # ближайший монитор
        info = _MonitorInfo(size=ctypes.sizeof(_MonitorInfo))
        if not monitor or not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return
        target = _half(info.work, right)
        if _user32.IsZoomed(window) or _user32.IsIconic(window):
            _user32.ShowWindow(window, 9)  # SW_RESTORE

        # Повторное измерение учитывает смену DPI при переносе на другой монитор.
        for _ in range(2):
            outer, visible = wintypes.RECT(), wintypes.RECT()
            if not _user32.GetWindowRect(window, ctypes.byref(outer)):
                return
            frame_ok = previous and _dwmapi.DwmGetWindowAttribute(
                window, 9, ctypes.byref(visible), ctypes.sizeof(visible)) == 0
            if not frame_ok:
                visible = outer
            if (visible.left, visible.top, visible.right, visible.bottom) == target:
                return
            left = target[0] + outer.left - visible.left
            top = target[1] + outer.top - visible.top
            end = target[2] + outer.right - visible.right
            bottom = target[3] + outer.bottom - visible.bottom
            _user32.SetWindowPos(window, None, left, top, end - left, bottom - top, 0x14)  # NOZORDER | NOACTIVATE
            _dwmapi.DwmFlush()
    finally:
        if previous:
            _set_thread_dpi(previous)


def place_browser_window(profile, *, right: bool, reference=None, pid=None):
    """Размещает только окно запущенного нами профиля, когда Windows его покажет."""
    if not _user32:
        return None
    window = _wait_for_window({pid}, 2) if pid else None
    if not window:
        window = _wait_for_window(set(find_browser_pids(profile)), 3)
    if window:
        _place(window, reference, right)
    return window
