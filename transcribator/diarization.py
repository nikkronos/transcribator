"""
Speaker diarization (who spoke when) via sherpa-onnx — torch-free, runs on CPU.

Pipeline: pyannote segmentation (ONNX) + speaker-embedding extractor (ONNX) +
fast clustering. Models are free, downloaded once from the sherpa-onnx GitHub
releases and cached locally. No HuggingFace token, no torch, no GPU required.

Public API:
    diarize_wav(wav_path, *, num_speakers=None, threshold=None, ...) -> list[SpeakerTurn]

Each SpeakerTurn is (start_sec, end_sec, speaker_id:int). Speaker ids are 0-based.
"""
from __future__ import annotations

import logging
import os
import tarfile
import tempfile
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# --- Free pretrained models (sherpa-onnx GitHub releases) ---
_SEG_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
_SEG_MEMBER_SUFFIX = "model.onnx"  # file inside the tar.bz2 we need
_SEG_FILENAME = "pyannote-segmentation-3-0.onnx"

# 3D-Speaker CAM++ embedding: fast on CPU and clusters better than TitaNet for
# diarization (measured on real recordings). Speaker embeddings are largely
# language-independent, so this works for Russian.
_EMB_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
)
_EMB_FILENAME = "3dspeaker_campplus_sv_zh-cn_16k-common.onnx"

# Clustering default (used only when the speaker count is NOT fixed): lower
# threshold -> more speakers, higher -> fewer. There is NO universal value — the
# resulting speaker count drifts with recording length (longer audio -> more
# clusters at the same threshold), so auto-detection is unreliable. ~1.1 is the
# right ballpark for CAM++ embeddings; always pass num_speakers when known.
_DEFAULT_THRESHOLD = 1.1


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: int  # 0-based speaker id


def models_dir() -> Path:
    """Directory where ONNX models are cached. Override with TRANSCRIBATOR_MODELS_DIR."""
    override = os.environ.get("TRANSCRIBATOR_MODELS_DIR")
    if override:
        d = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        d = Path(base) / "Transcribator" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _download(url: str, dest: Path, log: Callable[[str], None]) -> None:
    """Download url to dest atomically (.part then rename)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    log(f"Загрузка модели: {dest.name} …")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as f:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            read = 0
            last_pct = -10
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if total > 0:
                    pct = int(read / total * 100)
                    if pct - last_pct >= 10:
                        log(f"  {dest.name}: {pct}%")
                        last_pct = pct
        tmp.replace(dest)
        log(f"Готово: {dest.name}")
    finally:
        tmp.unlink(missing_ok=True)


def _ensure_segmentation_model(log: Callable[[str], None]) -> Path:
    target = models_dir() / _SEG_FILENAME
    if target.exists() and target.stat().st_size > 0:
        return target
    archive = models_dir() / "seg.tar.bz2"
    _download(_SEG_URL, archive, log)
    try:
        with tarfile.open(archive, "r:bz2") as tar:
            member = next(
                (m for m in tar.getmembers() if m.name.endswith(_SEG_MEMBER_SUFFIX)),
                None,
            )
            if member is None:
                raise RuntimeError("model.onnx не найден в архиве сегментации.")
            with tar.extractfile(member) as src, target.open("wb") as dst:  # type: ignore[union-attr]
                dst.write(src.read())
    finally:
        archive.unlink(missing_ok=True)
    return target


def _ensure_embedding_model(log: Callable[[str], None]) -> Path:
    target = models_dir() / _EMB_FILENAME
    if target.exists() and target.stat().st_size > 0:
        return target
    _download(_EMB_URL, target, log)
    return target


def ensure_models(log: Callable[[str], None] | None = None) -> tuple[Path, Path]:
    """Download (once) and return (segmentation_model, embedding_model) paths."""
    _log = log or (lambda m: logger.info("%s", m))
    seg = _ensure_segmentation_model(_log)
    emb = _ensure_embedding_model(_log)
    return seg, emb


def _read_wav_mono(path: Path, expected_rate: int) -> np.ndarray:
    """Read a 16-bit PCM mono wav as float32 in [-1, 1]. Raises if format mismatches."""
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        rate = w.getframerate()
        width = w.getsampwidth()
        if channels != 1:
            raise ValueError(f"Ожидался моно-wav, получено каналов: {channels}")
        if rate != expected_rate:
            raise ValueError(f"Ожидался {expected_rate} Гц, получено: {rate}")
        if width != 2:
            raise ValueError(f"Ожидался 16-бит PCM, получено байт/сэмпл: {width}")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def diarize_wav(
    wav_path: str | Path,
    *,
    num_speakers: int | None = None,
    threshold: float | None = None,
    num_threads: int | None = None,
    progress_callback: Callable[[float], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> list[SpeakerTurn]:
    """
    Diarize a 16 kHz mono wav. Returns speaker turns sorted by start time.

    num_speakers: if known (>0), force exactly this many speakers — strongly
                  recommended, since auto-detection over-segments on long files.
    threshold:    clustering distance used only when num_speakers is not set
                  (default 0.7). Lower -> more speakers.
    num_threads:  CPU threads (default: ~2/3 of cores) — diarization is the slow,
                  CPU-bound step, so more threads = faster.
    """
    import sherpa_onnx as so  # imported lazily: heavy native lib

    _log = log or (lambda m: logger.info("%s", m))
    seg_model, emb_model = ensure_models(_log)

    if num_threads is None:
        num_threads = max(2, min(8, (os.cpu_count() or 4) * 2 // 3))
    thr = _DEFAULT_THRESHOLD if threshold is None else float(threshold)
    n_clusters = int(num_speakers) if (num_speakers and num_speakers > 0) else -1

    config = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(seg_model)
            ),
            num_threads=num_threads,
            provider="cpu",
        ),
        embedding=so.SpeakerEmbeddingExtractorConfig(
            model=str(emb_model),
            num_threads=num_threads,
            provider="cpu",
        ),
        clustering=so.FastClusteringConfig(num_clusters=n_clusters, threshold=thr),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError(
            "Конфигурация диаризации не прошла валидацию (проверьте модели)."
        )

    sd = so.OfflineSpeakerDiarization(config)
    samples = _read_wav_mono(Path(wav_path), sd.sample_rate)

    if progress_callback is not None:
        def _cb(num_processed: int, num_total: int) -> int:
            if num_total > 0:
                progress_callback(min(100.0, num_processed / num_total * 100.0))
            return 0

        result = sd.process(samples, callback=_cb)
    else:
        result = sd.process(samples)

    turns = [
        SpeakerTurn(start=float(s.start), end=float(s.end), speaker=int(s.speaker))
        for s in result.sort_by_start_time()
    ]
    _log(
        f"Диаризация: найдено реплик={len(turns)}, "
        f"спикеров={len({t.speaker for t in turns})}."
    )
    return turns


def assign_speakers(
    segments: list[dict],
    turns: list[SpeakerTurn],
) -> None:
    """
    Annotate each transcript segment (dict with 'start','end') in place with a
    'speaker' label ("Спикер N", 1-based) by maximum time-overlap with diarization
    turns. Segments with no overlap get the nearest turn's speaker.
    """
    if not turns:
        for seg in segments:
            seg["speaker"] = "Спикер 1"
        return

    for seg in segments:
        s_start = float(seg.get("start", 0.0))
        s_end = float(seg.get("end", s_start))
        best_overlap = 0.0
        best_speaker: int | None = None
        for t in turns:
            overlap = min(s_end, t.end) - max(s_start, t.start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = t.speaker
        if best_speaker is None:
            # No overlap: fall back to the temporally nearest turn.
            mid = (s_start + s_end) / 2.0
            best_speaker = min(
                turns,
                key=lambda t: min(abs(mid - t.start), abs(mid - t.end)),
            ).speaker
        seg["speaker"] = f"Спикер {best_speaker + 1}"
