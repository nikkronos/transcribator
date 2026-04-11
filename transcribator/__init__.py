# Transcribator: local audio/video to text (Russian), output txt + json with timestamps.

import sys

if sys.platform == "win32":
    from ._win_cuda_dlls import register_nvidia_dll_directories

    register_nvidia_dll_directories()
