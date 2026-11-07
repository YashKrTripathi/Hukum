"""Secret storage in the Windows Credential Manager (advapi32 Cred* API). Secrets never touch the settings file,
the database, logs or AI prompts. On non-Windows machines (CI tests only) an in-memory dict stands in."""
import ctypes
import os
import sys

_mem = {}

if sys.platform == "win32":
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    _adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredFree.argtypes = [ctypes.c_void_p]
    CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2

    def write(name, secret):
        blob = secret.encode("utf-16-le")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIAL()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = name
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "hukum"
        if not _adv.CredWriteW(ctypes.byref(cred), 0):
            raise OSError(f"Credential Manager write failed ({ctypes.get_last_error()})")

    def read(name):
        p = ctypes.POINTER(CREDENTIAL)()
        if not _adv.CredReadW(name, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
            return None
        try:
            c = p.contents
            raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            _adv.CredFree(p)

    def delete(name):
        _adv.CredDeleteW(name, CRED_TYPE_GENERIC, 0)
else:
    def write(name, secret):
        _mem[name] = secret

    def read(name):
        return _mem.get(name)

    def delete(name):
        _mem.pop(name, None)
