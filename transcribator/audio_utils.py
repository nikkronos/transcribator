"""
Extract or normalize audio for transcription.
Uses ffmpeg for video->audio and for normalizing to 16k mono wav (optional).
"""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensions that are typically video (need extraction)
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv", ".m4v"}
# Voice/audio that need conversion to wav for whisper (e.g. Telegram .oga)
CONVERT_TO_WAV_EXTENSIONS = {".oga", ".ogg"}
# faster-whisper works well with wav; we convert to 16k mono for consistency
SAMPLE_RATE = 16000
CHANNELS = 1


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ensure_audio_path(input_path: str | Path) -> tuple[Path, bool]:
    """
    Return path to an audio file suitable for faster-whisper.
    If input is video, extract audio to a temp wav file (caller should clean up).
    If input is audio, return as-is (faster-whisper accepts common formats).
    Returns (path_to_audio, is_temporary).
    """
    path = Path(input_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        if not _ffmpeg_available():
            raise RuntimeError(
                "ffmpeg is required to process video files. Install ffmpeg and add it to PATH."
            )
        return _extract_audio_to_temp(path), True
    if suffix in CONVERT_TO_WAV_EXTENSIONS:
        if not _ffmpeg_available():
            raise RuntimeError(
                "ffmpeg is required to process this audio format. Install ffmpeg and add it to PATH."
            )
        return _convert_audio_to_wav(path), True
    return path, False


def _extract_audio_to_temp(video_path: Path) -> Path:
    """Extract audio from video to a temporary 16k mono wav file."""
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    wav_path = Path(wav_path)
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-loglevel",
            "error",
            "-nostats",
            str(wav_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info("Extracted audio from video to %s", wav_path)
        return wav_path
    except subprocess.CalledProcessError as e:
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed to extract audio: {e.stderr or e}") from e


def _convert_audio_to_wav(audio_path: Path) -> Path:
    """Convert audio (e.g. .oga) to temporary 16k mono wav."""
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    wav_path = Path(wav_path)
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-loglevel",
            "error",
            "-nostats",
            str(wav_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info("Converted audio to %s", wav_path)
        return wav_path
    except subprocess.CalledProcessError as e:
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed to convert audio: {e.stderr or e}") from e
