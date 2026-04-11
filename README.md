# Transcribator

Локальная утилита для транскрибации аудио и видео в текст (русский). Результаты сохраняются в `.txt` и `.json` с таймкодами — удобно передавать в AI-агента для рефлексии по созвонам и аналитики.

- **Вход:** локальные файлы (аудио и видео), можно указать несколько за один запуск.
- **Выход:** для каждого файла создаются `имя_файла.txt` (весь текст) и `имя_файла.json` (сегменты с полями `start`, `end`, `text`).
- **Режим:** полностью локально (офлайн), язык — русский.

## Требования

- **Python 3.10+**
- **ffmpeg** — для извлечения аудио из видео (должен быть в PATH).
- Достаточно RAM и места на диске для модели Whisper (модель `small` — порядка 500 MB).
- **GPU NVIDIA (опционально):** для ускорения в GUI/CLI через CUDA на Windows обычно нужны pip-пакеты `nvidia-cublas-cu12` и `nvidia-cudnn-cu12` (~1.2 GB). Подробности — [docs/gui-and-gpu-windows.md](docs/gui-and-gpu-windows.md).

## Установка

1. Клонируй репозиторий и перейди в папку проекта.

2. Создай виртуальное окружение и установи зависимости:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Убедись, что **ffmpeg** установлен и доступен в PATH (для видео):

```powershell
ffmpeg -version
```

Если ffmpeg не установлен: скачай с [ffmpeg.org](https://ffmpeg.org/download.html) или через `winget install ffmpeg` (Windows) и добавь в PATH.

4. **Ускорение на GPU (Windows, NVIDIA):** при необходимости установи в том же `.venv`:

```powershell
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

При импорте пакета `transcribator` DLL из `site-packages\nvidia\...\bin` регистрируются автоматически (см. [docs/gui-and-gpu-windows.md](docs/gui-and-gpu-windows.md)).

## Документация

| Документ | Содержание |
|----------|------------|
| [docs/gui-and-gpu-windows.md](docs/gui-and-gpu-windows.md) | GUI: прогресс, устройство, устойчивость; GPU/CUDA на Windows; переменные окружения ядра; журнал `gui_crash.log`; устранение неполадок |
| [docs/bot.md](docs/bot.md) | Telegram-бот: переменные, systemd, запуск на сервере |
| [docs/agent-onboarding.md](docs/agent-onboarding.md) | Краткий онбординг для агента |

## Использование

### Вариант 1: Окно для десктопа (удобнее)

Из корня проекта с активированным `.venv`:

```powershell
python -m transcribator.gui
```

Откроется окно: добавь файлы (аудио/видео), при необходимости укажи папку для результатов, **модель** и **устройство** (`auto` / `cuda` / `cpu`), нажми «Запустить транскрибацию». Лог и **прогресс (процент, ETA, очередь)** — в том же окне.

Двойной щелчок по `Запуск Transcribator.bat` в корне проекта — то же окно через `pythonw` (без консоли). Если окно «тихо» закрылось, см. журнал: `%LOCALAPPDATA%\Transcribator\gui_crash.log` (подробнее в [docs/gui-and-gpu-windows.md](docs/gui-and-gpu-windows.md)).

### Вариант 2: Командная строка (CLI)

```powershell
# Один файл
python -m transcribator путь/к/аудио.mp3

# Несколько файлов
python -m transcribator файл1.mp3 файл2.mp4 запись.m4a

# Сохранить результаты в отдельную папку
python -m transcribator файл1.mp3 -o папка_результатов

# Другая модель (base — быстрее, medium — точнее)
python -m transcribator файл.mp3 -m base

# Подробный вывод
python -m transcribator файл.mp3 -v
```

Результаты по умолчанию создаются рядом с исходным файлом: `имя_файла.txt` и `имя_файла.json`. При указании `-o папка` оба файла пишутся в эту папку.

### Вариант 3: Telegram-бот (на сервере)

Перешли или отправь боту голосовое сообщение — он пришлёт текст (только русский, только текст в ответ). **Сейчас бот отключён** (не запущен); инструкции по включению/выключению — в [docs/bot.md](docs/bot.md).

- **Где живёт:** тот же репозиторий; бот предназначен для запуска на сервере (например, Timeweb).
- **Требования:** токен бота (создать через [@BotFather](https://t.me/BotFather)), на сервере — Python 3.10+, ffmpeg, достаточная RAM для модели.
- **Запуск:** задать переменную окружения `TRANSCRIBATOR_BOT_TOKEN` (или `BOT_TOKEN`), затем `python -m transcribator.bot`. Подробнее — в [docs/bot.md](docs/bot.md).

## Формат JSON

```json
{
  "source_file": "созвон.mp3",
  "language": "ru",
  "model": "small",
  "segments": [
    { "start": 0.0, "end": 2.5, "text": "Привет, на связи." },
    { "start": 2.5, "end": 5.1, "text": "Давай обсудим план." }
  ]
}
```

## Структура проекта

- `transcribator/` — пакет (core, CLI, GUI, **бот для Telegram**, работа с аудио; `_win_cuda_dlls.py` — DLL для CUDA на Windows).
- `docs/` — база знаний и спецификации.
- `ROADMAP_TRANSCRIBATOR.md`, `DONE_LIST_TRANSCRIBATOR.md`, `SESSION_SUMMARY_*.md` — по правилам Cursor_Projects.

## Репозиторий

Отдельный репозиторий (не в составе Cursor_Projects). После создания репо на GitHub можно добавить remote и пушить из этой папки.
