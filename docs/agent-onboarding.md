# Онбординг агента: Transcribator

## Назначение проекта

Локальная утилита для транскрибации аудио и видео в текст (русский). Результаты сохраняются в .txt и .json (с таймкодами) для последующего анализа через AI-агента (рефлексия по созвонам, подсветки, аналитика). В том же репозитории — **Telegram-бот**: голосовое сообщение → текст (запуск на сервере).

## Стек

- Python 3.10+ (рабочее окружение владельца — 3.14; учти: у torch нет CUDA-колёс под 3.14, поэтому диаризатор намеренно torch-free)
- faster-whisper (локальное распознавание речи; на GPU через CTranslate2, не torch)
- sherpa-onnx (диаризация «кто говорит»: ONNX, без torch/токенов, CPU; модуль `transcribator/diarization.py`)
- ffmpeg (внешняя зависимость) — извлечение аудио из видео, конвертация .oga (голосовые Telegram), 16 кГц моно WAV для диаризации
- aiogram 3 — только для Telegram-бота

## Структура проекта

- `ROADMAP_TRANSCRIBATOR.md` — планы
- `DONE_LIST_TRANSCRIBATOR.md` — выполненные задачи
- `SESSION_SUMMARY_YYYY-MM-DD.md` — последняя сессия
- `docs/specs/` — спецификации
- **`docs/gui-and-gpu-windows.md`** — GUI (прогресс, устройство, стабильность), GPU/CUDA на Windows, переменные окружения ядра, `gui_crash.log`
- `docs/bot.md` — запуск и деплой Telegram-бота
- Пакет `transcribator/`: core, cli, gui, **bot** (Telegram), **diarization** (sherpa-onnx), audio_utils, `_win_cuda_dlls.py` (Windows + CUDA)

## Правила

- Следовать корневым `CLAUDE.md`, `Main_docs/RULES.md` и `Main_docs/AGENT_PROMPTS.md`.
- Репозиторий: отдельный новый репо (не AI_Projects).
- Коммиты и push выполняет пользователь по командам от агента.
- Секреты не хардкодить; при появлении ключей — env или аргументы.

## Полезные команды (примеры)

```powershell
cd "C:\Users\krono\OneDrive\Рабочий стол\AI_Projects\Projects\Transcribator"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m transcribator path\to\audio.mp3 path\to\video.mp4
python -m transcribator.gui
# Бот (на сервере, с токеном в env):
python -m transcribator.bot
```

---

**Последнее обновление:** 2026-06-18
