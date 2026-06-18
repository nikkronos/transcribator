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

from .audio_utils import ensure_audio_path, ensure_wav_16k_mono

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
            diarize=kwargs.get("diarize", False),
            num_speakers=kwargs.get("num_speakers"),
            diar_threshold=kwargs.get("diar_threshold"),
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


def _format_clock(seconds: float) -> str:
    """Seconds -> mm:ss (or h:mm:ss) for readable transcripts."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _build_plain_text(segments_data: list[dict[str, Any]]) -> str:
    """Single block of text (no speakers) — original .txt format."""
    return " ".join(s["text"].strip() for s in segments_data).strip()


def _build_diarized_text(segments_data: list[dict[str, Any]]) -> str:
    """Group consecutive same-speaker segments into readable, labelled turns."""
    turns: list[tuple[str, float, list[str]]] = []
    for s in segments_data:
        speaker = s.get("speaker", "Спикер 1")
        text = s["text"].strip()
        if turns and turns[-1][0] == speaker:
            turns[-1][2].append(text)
        else:
            turns.append((speaker, float(s.get("start", 0.0)), [text]))
    blocks = [
        f"[{_format_clock(start)}] {speaker}:\n{' '.join(t for t in texts if t).strip()}"
        for speaker, start, texts in turns
    ]
    return ("\n\n".join(blocks).strip() + "\n") if blocks else ""


def _segments_by_speaker(whisper_segments: list[Any], turns: list[Any]) -> list[dict[str, Any]]:
    """
    Build speaker-coherent segments from Whisper segments + diarization turns.

    Each word is assigned to a speaker; a Whisper segment is split wherever the
    speaker changes between consecutive words. This fixes the coarse "one speaker
    per long segment" merge (questions glued to answers, turns torn apart).
    Falls back to whole-segment assignment if a segment has no word timestamps.
    """
    from .diarization import speaker_label

    out: list[dict[str, Any]] = []
    for seg in whisper_segments:
        words = getattr(seg, "words", None) or []
        if not words:
            out.append(
                {
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": seg.text.strip(),
                    "speaker": speaker_label(seg.start, seg.end, turns),
                }
            )
            continue
        cur: dict[str, Any] | None = None
        for w in words:
            w_start = w.start if w.start is not None else (cur["end"] if cur else seg.start)
            w_end = w.end if w.end is not None else w_start
            token = (w.word or "").strip()
            if not token:
                continue
            label = speaker_label(w_start, w_end, turns)
            if cur is None or cur["speaker"] != label:
                if cur is not None:
                    out.append(cur)
                cur = {
                    "start": round(w_start, 2),
                    "end": round(w_end, 2),
                    "text": token,
                    "speaker": label,
                }
            else:
                cur["end"] = round(w_end, 2)
                cur["text"] = f"{cur['text']} {token}".strip()
        if cur is not None:
            out.append(cur)
    return out


def _smooth_short_turns(
    segments: list[dict[str, Any]], min_dur: float = 1.0
) -> list[dict[str, Any]]:
    """
    Remove crosstalk fragmentation: a very short segment (< min_dur) that sits
    between the other speaker's longer turns is almost always a misattributed
    word, so relabel it to the longer adjacent speaker, then merge consecutive
    same-speaker segments. Keeps normal-length turns intact.
    """
    if len(segments) < 3:
        return segments
    work = [dict(s) for s in segments]
    for i, s in enumerate(work):
        if (s["end"] - s["start"]) >= min_dur:
            continue
        prev = work[i - 1] if i > 0 else None
        nxt = work[i + 1] if i < len(work) - 1 else None
        if prev and nxt:
            cand = prev if (prev["end"] - prev["start"]) >= (nxt["end"] - nxt["start"]) else nxt
        else:
            cand = prev or nxt
        if cand and cand["speaker"] != s["speaker"]:
            s["speaker"] = cand["speaker"]
    merged: list[dict[str, Any]] = []
    for s in work:
        if merged and merged[-1]["speaker"] == s["speaker"]:
            merged[-1]["end"] = s["end"]
            merged[-1]["text"] = f"{merged[-1]['text']} {s['text']}".strip()
        else:
            merged.append(dict(s))
    return merged


def _transcribe_file_impl(
    input_path: Path,
    *,
    output_dir: Path | None,
    model_name: str,
    device: str,
    compute_type: str,
    language: str,
    progress_callback: Callable[[float | None, float | None], None] | None,
    diarize: bool = False,
    num_speakers: int | None = None,
    diar_threshold: float | None = None,
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
        # Diarization needs a 16 kHz mono wav; reuse the same audio for Whisper.
        if diarize:
            audio_path, is_temp = ensure_wav_16k_mono(input_path)
        else:
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
            # Word timestamps only when diarizing: needed to split a Whisper
            # segment at the exact point where the speaker changes.
            word_timestamps=diarize,
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

        num_speakers_found = 0
        segments_data: list[dict[str, Any]] | None = None
        if diarize:
            from .diarization import diarize_wav

            logger.info("Диаризация %s…", input_path.name)
            try:
                turns = diarize_wav(
                    audio_path,
                    num_speakers=num_speakers,
                    threshold=diar_threshold,
                    log=lambda m: logger.info("%s", m),
                )
                # Word-level split: speaker assigned per word, segments cut at
                # speaker changes (accurate turn boundaries), then short crosstalk
                # fragments smoothed away.
                segments_data = _smooth_short_turns(_segments_by_speaker(segments, turns))
                num_speakers_found = len({t.speaker for t in turns})
            except Exception:
                logger.exception(
                    "Диаризация не удалась для %s — сохраняю без спикеров.",
                    input_path.name,
                )
                diarize = False

        if segments_data is None:
            segments_data = [
                {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in segments
            ]

        full_text = (
            _build_diarized_text(segments_data)
            if diarize
            else _build_plain_text(segments_data)
        )
        out_json_data: dict[str, Any] = {
            "source_file": str(input_path.name),
            "language": detected_lang,
            "model": model_name,
            "diarization": bool(diarize),
            "num_speakers": num_speakers_found,
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


def _outputs_look_valid(out_txt: Path, out_json: Path) -> bool:
    """Best-effort validation for already produced outputs."""
    if not out_txt.exists() or not out_json.exists():
        return False
    try:
        if out_txt.stat().st_size <= 0 or out_json.stat().st_size <= 0:
            return False
    except OSError:
        return False

    try:
        payload = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return False
    return True


def transcribe_file(
    input_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    model_name: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    language: str = "ru",
    progress_callback: Callable[[float | None, float | None], None] | None = None,
    isolate_process: bool = False,
    max_transcribe_seconds: int | None = None,
    diarize: bool = False,
    num_speakers: int | None = None,
    diar_threshold: float | None = None,
) -> tuple[Path, Path]:
    """
    Transcribe one audio/video file. Writes .txt and .json next to the file
    (or into output_dir if given). Returns (path_txt, path_json).

    Diarization (optional):
    - diarize=True adds speaker labels ("кто говорит"). The .txt is grouped into
      readable speaker turns; each .json segment gets a "speaker" field. Uses the
      torch-free sherpa-onnx diarizer (CPU); models download once and are cached.
    - num_speakers: force an exact speaker count if known (else inferred).
    - diar_threshold: clustering threshold (lower -> more speakers; default ~0.5).
    If diarization fails, output falls back to the plain (no-speaker) format.

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
    final_out_dir = (out_dir or input_path.parent).resolve()
    out_txt = final_out_dir / f"{input_path.stem}.txt"
    out_json = final_out_dir / f"{input_path.stem}.json"

    if max_transcribe_seconds is None:
        try:
            max_wall = int(
                os.environ.get("TRANSCRIBATOR_MAX_TRANSCRIBE_SECONDS", "0") or "0"
            )
        except ValueError:
            max_wall = 0
    else:
        max_wall = max(0, int(max_transcribe_seconds))

    run_isolated = isolate_process or max_wall > 0

    if run_isolated:
        if progress_callback is not None:
            logger.warning(
                "Транскрибация выполняется в отдельном процессе "
                "(isolate_process=%s, max_transcribe_seconds=%s): "
                "прогресс-колбэк отключён для этого файла.",
                isolate_process,
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
            "diarize": diarize,
            "num_speakers": num_speakers,
            "diar_threshold": diar_threshold,
        }
        proc = ctx.Process(target=_mp_transcribe_runner, args=(result_queue, proc_kwargs))
        proc.start()
        if max_wall > 0:
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
        else:
            proc.join()

        if proc.exitcode not in (0, None):
            if _outputs_look_valid(out_txt, out_json):
                logger.warning(
                    "Child process exited with code %s but output files look valid: %s, %s",
                    proc.exitcode,
                    out_txt,
                    out_json,
                )
                return out_txt, out_json
            raise RuntimeError(
                f"Дочерний процесс транскрибации завершился аварийно "
                f"(exit code {proc.exitcode})."
            )
        try:
            status, *payload = result_queue.get(timeout=30 if max_wall > 0 else 10)
        except Exception as e:
            if _outputs_look_valid(out_txt, out_json):
                logger.warning(
                    "Child process did not return queue result but output files look valid: %s, %s",
                    out_txt,
                    out_json,
                )
                return out_txt, out_json
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
        diarize=diarize,
        num_speakers=num_speakers,
        diar_threshold=diar_threshold,
    )
