"""
Telegram bot: forward a voice message, get text back (Russian).
Runs on server. Requires BOT_TOKEN in env.
"""
import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, Voice

from .core import transcribe_file

logger = logging.getLogger(__name__)
router = Router()

# Model for server: small is a good balance (quality / speed / RAM)
BOT_MODEL = os.environ.get("TRANSCRIBATOR_BOT_MODEL", "small")


def _get_token() -> str:
    token = os.environ.get("TRANSCRIBATOR_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Set TRANSCRIBATOR_BOT_TOKEN or BOT_TOKEN in the environment."
        )
    return token


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет. Перешли или отправь голосовое сообщение — пришлю текст (расшифровка, русский)."
    )


@router.message(F.voice)
async def on_voice(message: Message) -> None:
    voice: Voice = message.voice
    if voice.duration and voice.duration > 60 * 20:  # 20 min
        await message.reply("Голосовое дольше 20 минут пока не обрабатываю. Сократи или порежь.")
        return

    status = await message.reply("Обрабатываю…")
    tmpdir = tempfile.mkdtemp(prefix="transcribator_bot_")
    try:
        oga_path = Path(tmpdir) / "voice.oga"
        await message.bot.download(voice.file_id, oga_path)

        out_txt, _ = transcribe_file(
            oga_path,
            output_dir=Path(tmpdir),
            model_name=BOT_MODEL,
            device="cpu",
            language="ru",
        )
        text = out_txt.read_text(encoding="utf-8").strip()
        if not text:
            await status.edit_text("Текст не распознан. Попробуй записать короче или чётче.")
            return
        # Telegram message limit 4096
        if len(text) > 4000:
            text = text[:3997] + "..."
        await status.edit_text(text)
    except FileNotFoundError:
        logger.exception("Voice file error")
        await status.edit_text("Ошибка: не удалось сохранить файл.")
    except RuntimeError:
        logger.exception("Transcription error")
        await status.edit_text("Ошибка распознавания. Проверь, что на сервере установлен ffmpeg.")
    except Exception as e:
        logger.exception("Unexpected error")
        await status.edit_text("Произошла ошибка. Попробуй позже.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@router.message()
async def on_other(message: Message) -> None:
    await message.reply("Отправь или перешли голосовое сообщение — пришлю текст.")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = _get_token()
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


def run_bot() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run_bot()
