"""
Register NVIDIA CUDA DLL directories from pip wheels (nvidia-*-cu12) on Windows.

CTranslate2 loads cublas/cudnn at inference time; without add_dll_directory(),
Python may not search site-packages\\nvidia\\...\\bin, which causes:

    RuntimeError: Library cublas64_12.dll is not found or cannot be loaded

Call register_nvidia_dll_directories() before importing faster_whisper / ctranslate2.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_registered = False


def register_nvidia_dll_directories() -> None:
    global _registered
    if _registered or sys.platform != "win32":
        return
    add_dll = getattr(os, "add_dll_directory", None)
    if not callable(add_dll):
        return

    roots: list[Path] = []

    def _add_site_roots(path: Path) -> None:
        roots.append(path)
        lib_sp = path / "Lib" / "site-packages"
        if lib_sp.is_dir():
            roots.append(lib_sp)

    try:
        import site

        get_sp = getattr(site, "getsitepackages", None)
        if callable(get_sp):
            for p in get_sp():
                _add_site_roots(Path(p))
        get_usp = getattr(site, "getusersitepackages", None)
        if callable(get_usp):
            try:
                roots.append(Path(get_usp()))
            except Exception:
                pass
    except Exception:
        pass

    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "site-packages"
        if cand.is_dir():
            roots.append(cand)

    bin_dirs: list[str] = []
    seen: set[str] = set()
    for root in roots:
        nvidia = root / "nvidia"
        if not nvidia.is_dir():
            continue
        try:
            for bin_dir in nvidia.glob("*/bin"):
                if not bin_dir.is_dir():
                    continue
                key = str(bin_dir.resolve())
                if key in seen:
                    continue
                seen.add(key)
                bin_dirs.append(key)
                try:
                    add_dll(key)
                except OSError:
                    pass
        except OSError:
            pass

    # CTranslate2 may load CUDA DLLs in a way that still relies on PATH for
    # transitive dependencies; add_dll_directory alone is not always enough on Windows.
    if bin_dirs:
        path = os.environ.get("PATH", "")
        prefix = ";".join(bin_dirs)
        if path:
            os.environ["PATH"] = prefix + ";" + path
        else:
            os.environ["PATH"] = prefix

    _registered = True
