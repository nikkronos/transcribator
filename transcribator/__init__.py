# Transcribator: local audio/video to text (Russian), output txt + json with timestamps.

import os
import shutil
import sys
from pathlib import Path


def _register_bundled_ffmpeg() -> None:
    """Prepend bundled ffmpeg-*/bin to PATH if system ffmpeg is missing.

    Why: project ships a portable ffmpeg build next to the package; without this,
    GUI/CLI runs fail with 'ffmpeg is required' when system ffmpeg is not installed.
    """
    if shutil.which("ffmpeg"):
        return
    project_root = Path(__file__).resolve().parent.parent
    candidates = sorted(
        (p for p in project_root.glob("ffmpeg-*/bin") if (p / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")).exists()),
        reverse=True,
    )
    if not candidates:
        return
    bin_dir = str(candidates[0])
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


_register_bundled_ffmpeg()

if sys.platform == "win32":
    from ._win_cuda_dlls import register_nvidia_dll_directories

    register_nvidia_dll_directories()
