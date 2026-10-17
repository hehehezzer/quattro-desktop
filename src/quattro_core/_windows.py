"""Windows handle containment and inherited storage ACL validation; no ACL mutation."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache
import os
from pathlib import Path


@lru_cache(maxsize=1)
def _api():
    if os.name != "nt":
        raise OSError("Windows file APIs are unavailable")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    pointer = wintypes.LPVOID
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  pointer, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, pointer]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, pointer,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.GetTokenInformation.restype = wintypes.BOOL
    security.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(wintypes.LPWSTR)]
    security.ConvertSidToStringSidW.restype = wintypes.BOOL
    security.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(pointer), ctypes.POINTER(pointer), ctypes.POINTER(pointer),
        ctypes.POINTER(pointer), ctypes.POINTER(pointer)]
    security.GetNamedSecurityInfoW.restype = wintypes.DWORD
    security.GetAce.argtypes = [pointer, wintypes.DWORD, ctypes.POINTER(pointer)]
    security.GetAce.restype = wintypes.BOOL
    return kernel, security


def _sid_text(sid):
    kernel, security = _api()
    text = wintypes.LPWSTR()
    if not security.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return text.value
    finally:
        kernel.LocalFree(ctypes.cast(text, wintypes.LPVOID))


@lru_cache(maxsize=1)
def _current_sid():
    kernel, security = _api()
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not size.value:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return _sid_text(ctypes.cast(buffer, ctypes.POINTER(wintypes.LPVOID))[0])
    finally:
        kernel.CloseHandle(token)


def require_private_acl(path: Path) -> None:
    """Reject null, foreign-owner or broadly readable ACLs; do not change user permissions."""
    if any(getattr(os.lstat(part), "st_file_attributes", 0) & 0x400 for part in (path, *path.parents)):
        raise ValueError("storage paths cannot contain reparse points")
    kernel, security = _api()
    owner, dacl, descriptor = wintypes.LPVOID(), wintypes.LPVOID(), wintypes.LPVOID()
    result = security.GetNamedSecurityInfoW(str(path), 1, 0x00000005,
        ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if result:
        raise ctypes.WinError(result)
    try:
        allowed = {_current_sid(), "S-1-5-18", "S-1-5-32-544"}
        if not owner or _sid_text(owner) not in allowed or not dacl:
            raise ValueError("storage requires a private Windows ACL")
        # ACL header: revision/reserved/size/ace-count/reserved.
        count = ctypes.c_ushort.from_address(dacl.value + 4).value
        for index in range(count):
            ace = wintypes.LPVOID()
            if not security.GetAce(dacl, index, ctypes.byref(ace)):
                raise ctypes.WinError(ctypes.get_last_error())
            kind = ctypes.c_ubyte.from_address(ace.value).value
            flags = ctypes.c_ubyte.from_address(ace.value + 1).value
            if kind == 1:  # Deny entries cannot grant access.
                continue
            if kind != 0:
                raise ValueError("storage contains an unsupported Windows allow ACE")
            principal = _sid_text(ace.value + 8)
            # CREATOR OWNER is substituted for the creating principal on children.
            # Other inherit-only grants still expose future SQLite WAL/journal files.
            if flags & 0x08 and principal == "S-1-3-0":
                continue
            if principal not in allowed:
                raise ValueError("storage ACL must allow only the operator, SYSTEM and Administrators")
    finally:
        kernel.LocalFree(descriptor)


class _FileInformation(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


def read_file(root: Path, relative: Path, maximum: int):
    """Pin every directory without delete sharing; reject reparse points before reading."""
    import msvcrt
    import stat
    if not root.is_absolute() or relative.is_absolute() or any(p in {"..", "."} for p in relative.parts):
        raise ValueError("source path must remain relative to its root")
    kernel, _ = _api()
    handles = []
    descriptor = None
    try:
        path = Path(root.anchor)
        parts = [None, *root.parts[1:], *relative.parts]
        for index, part in enumerate(parts):
            if part is not None:
                path /= part
            directory = index != len(parts) - 1
            # Pin directories against both deletion and writable reparse mutation.
            # OPEN_REPARSE_POINT protects the component being opened, not its parents.
            handle = kernel.CreateFileW(str(path), 0x80000000, 1 if directory else 3, None, 3,
                0x00200000 | (0x02000000 if directory else 0), None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = _FileInformation()
            if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
                raise OSError("source path contains a reparse point or wrong file type")
        descriptor = msvcrt.open_osfhandle(handles[-1], os.O_RDONLY | os.O_BINARY)
        handles.pop()  # The CRT descriptor now owns the final handle.
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError("source file is not a bounded regular file")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(descriptor)
        if len(raw) > maximum or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise OSError("source changed during indexing")
        return raw.decode("utf-8"), after
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for handle in reversed(handles):
            kernel.CloseHandle(handle)
