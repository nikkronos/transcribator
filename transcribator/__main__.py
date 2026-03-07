"""
Entry point: python -m transcribator file1.mp3 file2.mp4 [--output-dir dir]
"""
from .cli import run

if __name__ == "__main__":
    raise SystemExit(run())
