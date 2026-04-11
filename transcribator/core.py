"""
Core transcription: load model, transcribe, write txt + json.
"""
import gc
import json
import logging
import multiprocessing as mp
import os
import subprocess
import time
import wave
from pathlib import Path
from typing import Any, Callable

from faster_whisper import WhisperModel

from .audio_utils import ensure_audio_path

logger = logging.getLogger(__name__)

# Default model: small is a good balance for Russian (quality/speed/size)
DEFAULT_MODEL = "small"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE_TYPE = "int8"  # smaller memory on CPU

# Long files: disable condition_on_previous_text by default to avoid decoder stalls
# (repetition / timestamp loops). Override with env TRANSCRIBATOR_CONDITION_PREVIOUS=1|0.
_DEFAULT_LONG_FILE_THRESHOLD_SEC = 1800.0


def _parse_env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _condition_on_previous_text(
    total_duration_sec: float | None, *, vad_enabled: bool
) -> bool:
    """
    Whisper can get stuck when condition_on_previous_text=True (repetition / timestamp loops).
    With Silero VAD enabled we default to False — usually safer and still good quality on speech.
    If VAD is off, use duration threshold. Override anytime with TRANSCRIBATOR_CONDITION_PREVIOUS.
    """
    env = os.environ.get("TRANSCRIBATOR_CONDITION_PREVIOUS")
    if env is not None:
        return _parse_env_bool("TRANSCRIBATOR_CONDITION_PREVIOUS", True)
    if vad_enabled:
        return False
    try:
        thr = float(
            os.environ.get(
                "TRANSCRIBATOR_LONG_FILE_SECONDS",
                str(_DEFAULT_LONG_FILE_THRESHOLD_SEC),
            )
        )
    except ValueError:
        thr = _DEFAULT_LONG_FILE_THRESHOLD_SEC
    if total_duration_sec is None:
        return True
    return total_duration_sec < thr


def _mp_transcribe_runner(result_queue: "mp.Queue", kwargs: dict[str, Any]) -> None:
    """Child entry for isolated transcription (Windows spawn)."""
    try:
        in_path = Path(kwargs["input_path"])
        out_dir = Path(kwargs["output_dir"]) if kwargs.get("output_dir") else None
        paths = _transcribe_file_impl(
            in_path,
            output_dir=out_dir,
            model_name=kwargs["model_name"],
            device=kwargs["device"],
            compute_type=kwargs["compute_type"],
            language=kwargs["language"],
            progress_callback=None,
        )
        result_queue.put(("ok", str(paths[0]), str(paths[1])))
    except Exception as e:
        result_queue.put(("err", f"{type(e).__name__}: {e}"))


def _probe_media_duration_seconds(path: Path) -> float | None:
    """
    Best-effort media duration probe in seconds.
    Returns None if duration cannot be determined.
    """
    try:
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                if rate > 0:
                    return frames / rate
                return None
    except Exception:
        logger.debug("Could not read wav duration for %s", path, exc_info=True)

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        value = (result.stdout or "").strip()
        if not value:
            return None
        duration = float(value)
        if duration > 0:
            return duration
        return None
    except Exception:
        logger.debug("Could not probe duration for %s", path, exc_info=True)
        return None


def _transcribe_file_impl(
    input_path: Path,
    *,
    output_dir: Path | None,
    model_name: str,
    device: str,
    compute_type: str,
    language: str,
    progress_callback: Callable[[float | None, float | None], None] | None,
) -> tuple[Path, Path]:
    """Internal transcription (single process). See transcribe_file() for env options."""
    if not input_path.exists():
        raise FileNotFoundError(f"File not found: {input_path}")

    out_dir = (output_dir or input_path.parent).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = input_path.stem
    out_txt = out_dir / f"{base_name}.txt"
    out_json = out_dir / f"{base_name}.json"

    temp_audio: Path | None = None
    is_temp = False
    model: WhisperModel | None = None
    try:
        audio_path, is_temp = ensure_audio_path(input_path)
        if is_temp:
            temp_audio = audio_path
        total_duration = _probe_media_duration_seconds(audio_path)
        vad_on = not _parse_env_bool("TRANSCRIBATOR_DISABLE_VAD", False)
        condition_prev = _condition_on_previous_text(
            total_duration, vad_enabled=vad_on
        )

        logger.info(
            "Transcribe %s: vad_filter=%s, condition_on_previous_text=%s, "
            "probed_duration_sec=%s",
            input_path.name,
            vad_on,
            condition_prev,
            total_duration,
        )

        if progress_callback is not None:
            progress_callback(0.0, None)

        logger.info("Loading model %s (%s, %s)...", model_name, device, compute_type)
        model = WhisperModel(model_name, device=device, compute_type=compute_type)

        logger.info("Transcribing %s...", input_path.name)
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=vad_on,
            condition_on_previous_text=condition_prev,
        )
        started_at = time.perf_counter()
        first_segment_at: float | None = None
        segments = []
        for segment in segments_iter:
            if first_segment_at is None:
                first_segment_at = time.perf_counter()
                logger.info(
                    "First segment after %.1fs (file=%s)",
                    first_segment_at - started_at,
                    input_path.name,
                )
            segments.append(segment)
            if progress_callback is None:
                continue
            if total_duration is None or total_duration <= 0:
                progress_callback(None, None)
                continue
            processed_seconds = min(float(segment.end), total_duration)
            progress = max(0.0, min(100.0, processed_seconds / total_duration * 100.0))
            elapsed = max(0.0, time.perf_counter() - started_at)
            eta_seconds: float | None = None
            if elapsed > 0 and processed_seconds > 0:
                speed = processed_seconds / elapsed
                if speed > 0:
                    eta_seconds = max(0.0, (total_duration - processed_seconds) / speed)
            progress_callback(progress, eta_seconds)

        detected_lang = getattr(info, "language", language) or language

        full_text = " ".join(s.text.strip() for s in segments).strip()
        segments_data = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments
        ]
        out_json_data: dict[str, Any] = {
            "source_file": str(input_path.name),
            "language": detected_lang,
            "model": model_name,
            "segments": segments_data,
        }

        out_txt.write_text(full_text, encoding="utf-8")
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(out_json_data, f, ensure_ascii=False, indent=2)

        logger.info("Written %s and %s", out_txt, out_json)
        if progress_callback is not None:
            progress_callback(100.0, 0.0)
        return (out_txt, out_json)
    finally:
        if model is not None:
            try:
                del model
            except Exception:
                logger.debug("Model cleanup failed", exc_info=True)
            gc.collect()
        if temp_audio and temp_audio.exists():
            try:
                temp_audio.unlink()
            except OSError as e:
                logger.warning("Could not remove temp file %s: %s", temp_audio, e)


def transcribe_file(
    input_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    model_name: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    language: str = "ru",
    progress_callback: Callable[[float | None, float | None], None] | None = None,
) -> tuple[Path, Path]:
    """
    Transcribe one audio/video file. Writes .txt and .json next to the file
    (or into output_dir if given). Returns (path_txt, path_json).

    Environment (optional):
    - TRANSCRIBATOR_MAX_TRANSCRIBE_SECONDS: if > 0, run in a separate process and
      kill it after this many seconds (progress_callback is ignored).
    - TRANSCRIBATOR_CONDITION_PREVIOUS: force 1/0 for Whisper condition_on_previous_text.
    - TRANSCRIBATOR_LONG_FILE_SECONDS: threshold (default 1800) below which
      condition_on_previous_text stays True when env above is unset.
    - TRANSCRIBATOR_DISABLE_VAD=1: disable Silero VAD pre-filter.

    Raises FileNotFoundError, RuntimeError on failure.
    """
    input_path = Path(input_path).resolve()
    out_dir = Path(output_dir).resolve() if output_dir else None

    try:
        max_wall = int(os.environ.get("TRANSCRIBATOR_MAX_TRANSCRIBE_SECONDS", "0") or "0")
    except ValueError:
        max_wall = 0

    if max_wall > 0:
        if progress_callback is not None:
            logger.warning(
                "TRANSCRIBATOR_MAX_TRANSCRIBE_SECONDS=%s: отдельный процесс, "
                "прогресс в GUI отключён для этого файла.",
                max_wall,
            )
        ctx = mp.get_context("spawn")
        result_queue: mp.Queue = ctx.Queue()
        proc_kwargs: dict[str, Any] = {
            "input_path": str(input_path),
            "output_dir": str(out_dir) if out_dir else None,
            "model_name": model_name,
            "device": device,
            "compute_type": compute_type,
            "language": language,
        }
        proc = ctx.Process(target=_mp_transcribe_runner, args=(result_queue, proc_kwargs))
        proc.start()
        proc.join(max_wall)
        if proc.is_alive():
            proc.terminate()
            proc.join(25)
            if proc.is_alive():
                proc.kill()
                proc.join(15)
            raise RuntimeError(
                f"Транскрибация остановлена по лимиту времени ({max_wall} с). "
                "Похоже на зависание декодера (известно для длинных файлов без VAD / "
                "с зацикливанием). Уже включены VAD и защита для длинных дорожек; "
                "при необходимости увеличьте TRANSCRIBATOR_MAX_TRANSCRIBE_SECONDS "
                "или конвертируйте файл в WAV и повторите."
            )
        try:
            status, *payload = result_queue.get(timeout=30)
        except Exception as e:
            raise RuntimeError(
                "Дочерний процесс завершился без результата (см. лог консоли)."
            ) from e
        if status == "err":
            raise RuntimeError(payload[0])
        return Path(payload[0]), Path(payload[1])

    return _transcribe_file_impl(
        input_path,
        output_dir=out_dir,
        model_name=model_name,
        device=device,
        compute_type=compute_type,
        language=language,
        progress_callback=progress_callback,
    )
