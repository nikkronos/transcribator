# Онбординг агента: Transcribator

## Назначение проекта

Локальная утилита для транскрибации аудио и видео в текст (русский). Результаты сохраняются в .txt и .json (с таймкодами) для последующего анализа через AI-агента (рефлексия по созвонам, подсветки, аналитика).

## Стек

- Python 3.10+
- faster-whisper (локальное распознавание речи)
- ffmpeg (внешняя зависимость) — извлечение аудио из видео

## Структура проекта

- `ROADMAP_TRANSCRIBATOR.md` — планы
- `DONE_LIST_TRANSCRIBATOR.md` — выполненные задачи
- `SESSION_SUMMARY_YYYY-MM-DD.md` — последняя сессия
- `docs/specs/` — спецификации (01-mvp-transcriber.md)
- Исходный код: корень или пакет `transcribator/` по усмотрению

## Правила

- Следовать Main_docs (RULES_CURSOR.md, QUICK_START_AGENT.md, AGENT_PROMPTS.md).
- Репозиторий: отдельный новый репо (не Cursor_Projects).
- Коммиты и push выполняет пользователь по командам от агента.
- Секреты не хардкодить; при появлении ключей — env или аргументы.

## Полезные команды (примеры)

```powershell
cd "C:\Users\krono\OneDrive\Рабочий стол\Cursor_Projects\Projects\Transcribator"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m transcribator path\to\audio.mp3 path\to\video.mp4
```

---

**Последнее обновление:** 2026-03-07
