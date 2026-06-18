"""
CLI for Transcribator: multiple files, optional output directory.
"""
import argparse
import logging
import sys
from pathlib import Path

from .core import transcribe_file

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe audio/video to text (Russian). Output: .txt and .json with timestamps."
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="One or more audio/video files to transcribe",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for output files (default: same as each input file)",
    )
    parser.add_argument(
        "-m",
        "--model",
        default="small",
        help="Whisper model size (tiny, base, small, medium, large-v3; default: small)",
    )
    parser.add_argument(
        "--device",
        choices=("cpu", "cuda"),
        default="cpu",
        help="Device (default: cpu)",
    )
    parser.add_argument(
        "--diarize",
        action="store_true",
        help="Speaker diarization: label who speaks (кто говорит) in .txt and .json",
    )
    parser.add_argument(
        "--speakers",
        type=int,
        default=None,
        help="Exact number of speakers if known (default: auto-detect)",
    )
    parser.add_argument(
        "--diar-threshold",
        type=float,
        default=None,
        help="Diarization clustering threshold (lower = more speakers; default ~0.5)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    return parser.parse_args(args)


def run(args: list[str] | None = None) -> int:
    parsed = parse_args(args)
    _setup_logging(parsed.verbose)

    failed = 0
    for path in parsed.files:
        path = path.resolve()
        if not path.exists():
            logger.error("File not found: %s", path)
            failed += 1
            continue
        if not path.is_file():
            logger.error("Not a file: %s", path)
            failed += 1
            continue
        try:
            transcribe_file(
                path,
                output_dir=parsed.output_dir,
                model_name=parsed.model,
                device=parsed.device,
                language="ru",
                diarize=parsed.diarize,
                num_speakers=parsed.speakers,
                diar_threshold=parsed.diar_threshold,
            )
        except FileNotFoundError as e:
            logger.error("%s", e)
            failed += 1
        except RuntimeError as e:
            logger.error("Transcription failed for %s: %s", path, e)
            failed += 1
        except Exception as e:
            logger.exception("Unexpected error for %s: %s", path, e)
            failed += 1

    if failed:
        return 1
    return 0
