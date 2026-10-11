"""Version-checked lifecycle supervisor for the optional Windows native helper."""
from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
from ctypes import wintypes
from pathlib import Path
from typing import Any


EXPECTED_GAME_SHA256 = "782b904a8f7bbdac1f7a18528f1a5c778691e5aa3087c37c351bf6912585175c"
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("GlblcntUsage", wintypes.DWORD), ("ProccntUsage", wintypes.DWORD),
                ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)), ("modBaseSize", wintypes.DWORD),
                ("hModule", wintypes.HMODULE), ("szModule", wintypes.WCHAR * 256),
                ("szExePath", wintypes.WCHAR * 260)]


def _kernel32():
    if os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel.Module32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W))
    kernel.Module32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W))
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel


def find_game_process() -> tuple[int, Path] | None:
    kernel = _kernel32()
    if kernel is None:
        return None
    snapshot = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return None
    entry = PROCESSENTRY32W(); entry.dwSize = ctypes.sizeof(entry)
    try:
        if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            return None
        while True:
            if entry.szExeFile.lower() == "transportfever2.exe":
                handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, entry.th32ProcessID)
                if handle:
                    try:
                        size = wintypes.DWORD(32768); buffer = ctypes.create_unicode_buffer(size.value)
                        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                            return int(entry.th32ProcessID), Path(buffer.value)
                    finally:
                        kernel.CloseHandle(handle)
            if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                return None
    finally:
        kernel.CloseHandle(snapshot)


def loaded_modules(process_id: int) -> list[Path]:
    kernel = _kernel32()
    if kernel is None:
        return []
    snapshot = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, process_id)
    if snapshot == INVALID_HANDLE_VALUE:
        return []
    entry = MODULEENTRY32W(); entry.dwSize = ctypes.sizeof(entry); result = []
    try:
        if kernel.Module32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                result.append(Path(entry.szExePath))
                if not kernel.Module32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel.CloseHandle(snapshot)
    return result


class NativeSupervisor:
    def __init__(self, mod_root: Path):
        self.mod_root = Path(mod_root)
        self.native = self.mod_root / "native"
        self.dll = self.native / "tpf2_control.dll"
        self.next_dll = self.native / "tpf2_control.next.dll"
        self.injector = self.native / "tpf2_control_injector.exe"

    def reconcile(self, allow_inject: bool = False) -> dict[str, Any]:
        process = find_game_process()
        if process is None:
            updated = False
            if self.next_dll.is_file():
                self.dll.parent.mkdir(parents=True, exist_ok=True)
                os.replace(self.next_dll, self.dll)
                updated = True
            return {"supervisor_state": "GAME_NOT_RUNNING", "native_update_applied": updated,
                    "native_update_pending": False, "process_id": None}
        process_id, executable = process
        modules = loaded_modules(process_id)
        loaded = next((path for path in modules if path.name.lower() == self.dll.name.lower()), None)
        result = {"process_id": process_id, "game_executable": str(executable),
                  "native_update_pending": self.next_dll.is_file(), "loaded_module": str(loaded) if loaded else None}
        if loaded:
            return {**result, "supervisor_state": "LOADED"}
        if not allow_inject:
            return {**result, "supervisor_state": "NOT_LOADED"}
        if not self.dll.is_file() or not self.injector.is_file():
            return {**result, "supervisor_state": "INJECTION_BLOCKED", "reason": "NATIVE_RUNTIME_MISSING"}
        actual = hashlib.sha256(executable.read_bytes()).hexdigest()
        if actual != EXPECTED_GAME_SHA256:
            return {**result, "supervisor_state": "INJECTION_BLOCKED", "reason": "GAME_SHA256_MISMATCH",
                    "actual_sha256": actual}
        completed = subprocess.run([str(self.injector), str(process_id), str(self.dll)], capture_output=True,
                                   text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        loaded = next((path for path in loaded_modules(process_id) if path.name.lower() == self.dll.name.lower()), None)
        return {**result, "supervisor_state": "LOADED" if completed.returncode == 0 and loaded else "INJECTION_FAILED",
                "loaded_module": str(loaded) if loaded else None, "injector_exit_code": completed.returncode,
                "injector_output": (completed.stdout + completed.stderr).strip()[-1000:]}
