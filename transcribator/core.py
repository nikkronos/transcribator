"""
Core transcription: load model, transcribe, write txt + json.
"""
import json
import logging
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

from .audio_utils import ensure_audio_path

logger = logging.getLogger(__name__)

# Default model: small is a good balance for Russian (quality/speed/size)
DEFAULT_MODEL = "small"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE_TYPE = "int8"  # smaller memory on CPU


def transcribe_file(
    input_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    model_name: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    language: str = "ru",
) -> tuple[Path, Path]:
    """
    Transcribe one audio/video file. Writes .txt and .json next to the file
    (or into output_dir if given). Returns (path_txt, path_json).

    Raises FileNotFoundError, RuntimeError on failure.
    """
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"File not found: {input_path}")

    out_dir = Path(output_dir).resolve() if output_dir else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = input_path.stem
    out_txt = out_dir / f"{base_name}.txt"
    out_json = out_dir / f"{base_name}.json"

    temp_audio: Path | None = None
    is_temp = False
    try:
        audio_path, is_temp = ensure_audio_path(input_path)
        if is_temp:
            temp_audio = audio_path

        logger.info("Loading model %s (%s, %s)...", model_name, device, compute_type)
        model = WhisperModel(model_name, device=device, compute_type=compute_type)

        logger.info("Transcribing %s...", input_path.name)
        segments_iter, info = model.transcribe(str(audio_path), language=language)
        segments = list(segments_iter)
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
        return (out_txt, out_json)
    finally:
        if temp_audio and temp_audio.exists():
            try:
                temp_audio.unlink()
            except OSError as e:
                logger.warning("Could not remove temp file %s: %s", temp_audio, e)
