# GUI, GPU (Windows) и устойчивость Transcribator

Полное описание десктопного окна, ускорения на NVIDIA под Windows, переменных окружения и поведения при сбоях. Для быстрого старта см. также [README.md](../README.md).

---

## 1. Окно GUI (`python -m transcribator.gui`, `Запуск Transcribator.bat`)

### Возможности

- Очередь файлов (несколько аудио/видео за один запуск).
- Папка вывода (опционально); по умолчанию — рядом с каждым исходным файлом.
- Выбор модели Whisper: `tiny`, `base`, `small`, `medium`, `large-v3`.
- **Устройство:** `auto` | `cuda` | `cpu`.
  - `auto`: проверка CUDA перед очередью; при успехе — GPU, иначе CPU и сообщение в лог.
  - `cuda` / `cpu`: принудительный режим (на `cuda` при ошибке драйвера для конкретного файла возможен fallback на CPU только в режиме `auto` по текущей логике GUI).
- **Прогресс:** процент и ETA по текущему файлу; общий прогресс очереди по числу файлов (`i/n` и суммарный %).
- **Heartbeat:** если долго нет новых сегментов от Whisper, в лог пишутся строки вида «обработка продолжается… Nс без нового сегмента» — это ожидание следующего сегмента, не обязательно зависание.

### Запуск без консоли

`Запуск Transcribator.bat` вызывает `pythonw.exe` — окно консоли не показывается. При ошибке старта срабатывает fallback на `python.exe` с `pause`.

### Журнал сбоев GUI (pythonw)

При исключениях в колбэках Tk и в обработчике очереди лога traceback дописывается в файл:

`%LOCALAPPDATA%\Transcribator\gui_crash.log`

В лог окна может выводиться подсказка с этим путём. Полезно, если приложение «тихо» закрывается без консоли.

### Устойчивость после транскрибации

- Воркер-транскрибация: по завершении очереди UI ждёт **`join`** потока (таймаут 120 с), затем разблокирует кнопку.
- В `core`: после каждого файла явное **`del model`** и **`gc.collect()`** для упорядоченного освобождения CUDA/CTranslate2.
- При необработанной ошибке в потоке в очередь отправляется `WorkerResult(success=False)`, чтобы кнопка не оставалась заблокированной.

---

## 2. GPU на Windows (NVIDIA, CUDA 12)

### Симптом без доработки окружения

Сообщения вида: `Library cublas64_12.dll is not found or cannot be loaded` — инференс падает на CPU или с ошибкой, хотя `WhisperModel(..., device='cuda')` иногда проходит.

### Решение: pip-колёса NVIDIA

В активированном `.venv` проекта:

```powershell
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

Подтянется и зависимость `nvidia-cuda-nvrtc-cu12`. Объём загрузки большой (~1.2 GB суммарно).

### Регистрация DLL и PATH

Пакеты кладут DLL в `Lib\site-packages\nvidia\*\bin`. На Windows одного `os.add_dll_directory` для CTranslate2 недостаточно: модуль **`transcribator/_win_cuda_dlls.py`** при импорте пакета:

- добавляет эти каталоги через `os.add_dll_directory`;
- **дописывает их в начало `PATH`**.

Вызов выполняется из **`transcribator/__init__.py`** до любых импортов `faster_whisper` в подмодулях (в т.ч. в `gui.py`).

### Проверка из корня проекта

```powershell
.\.venv\Scripts\python.exe -c "import transcribator; from faster_whisper import WhisperModel; WhisperModel('tiny', device='cuda', compute_type='int8'); print('ok')"
```

Для полного smoke-теста транскрибации см. README.

---

## 3. Ядро транскрибации (`transcribator/core.py`)

### Silero VAD

По умолчанию **`vad_filter=True`**: вырезаются длинные участки без речи, что ускоряет работу и снижает риск «залипания» декодера на тишине.

Отключить: **`TRANSCRIBATOR_DISABLE_VAD=1`**.

### `condition_on_previous_text`

У Whisper при **`condition_on_previous_text=True`** на длинных дорожках возможны редкие зацикливания (долго без новых сегментов).

Текущая логика:

- если задана **`TRANSCRIBATOR_CONDITION_PREVIOUS`** — трактуется как принудительное вкл/выкл (`1`/`true`/`yes`/`on` vs остальное);
- иначе при **включённом VAD** по умолчанию **`False`**;
- при **выключенном VAD** — **`True`** только для файлов короче порога **`TRANSCRIBATOR_LONG_FILE_SECONDS`** (по умолчанию **1800** с); для более длинных — `False`.

### Изолированный процесс и таймаут

Если **`TRANSCRIBATOR_MAX_TRANSCRIBE_SECONDS`** > 0, транскрибация выполняется в **отдельном процессе** (`spawn`); по истечении времени процесс принудительно завершается. В этом режиме **`progress_callback` не работает** (GUI не получит пошаговый прогресс для этого вызова).

---

## 4. Таблица переменных окружения (ядро + бот)

| Переменная | Где используется | Описание |
|------------|------------------|----------|
| `TRANSCRIBATOR_DISABLE_VAD` | core | `1` — отключить Silero VAD. |
| `TRANSCRIBATOR_CONDITION_PREVIOUS` | core | Явно включить/выключить `condition_on_previous_text` у Whisper. |
| `TRANSCRIBATOR_LONG_FILE_SECONDS` | core | Порог (секунды) для ветки без VAD (по умолчанию 1800). |
| `TRANSCRIBATOR_MAX_TRANSCRIBE_SECONDS` | core | >0 — транскрибация в дочернем процессе с лимитом времени; прогресс из GUI отключён. |
| `TRANSCRIBATOR_BOT_TOKEN` / `BOT_TOKEN` | bot | Токен Telegram-бота. |
| `TRANSCRIBATOR_BOT_MODEL` | bot | Модель для бота (по умолчанию `small`). |

Подробности по боту: [bot.md](bot.md).

---

## 5. Связанные файлы кода

| Файл | Назначение |
|------|------------|
| `transcribator/__init__.py` | Регистрация NVIDIA DLL на Windows при импорте пакета. |
| `transcribator/_win_cuda_dlls.py` | Поиск `site-packages\nvidia\*\bin`, `add_dll_directory`, префикс `PATH`. |
| `transcribator/core.py` | Транскрибация, VAD, опциональный изолированный процесс, освобождение модели. |
| `transcribator/gui.py` | UI, прогресс, устройство, воркер, `join`, лог сбоев, `main()`. |
| `transcribator/audio_utils.py` | ffmpeg: видео → wav, `.oga`/`.ogg` → wav. |
| `requirements.txt` | Базовые зависимости; комментарий про опциональные NVIDIA-пакеты для GPU. |

---

## 6. Устранение неполадок

| Проблема | Что проверить |
|----------|----------------|
| CUDA ошибка / CPU вместо GPU | Установлены ли `nvidia-cublas-cu12` и `nvidia-cudnn-cu12`; перезапуск приложения после установки; `nvidia-smi`; файл `%LOCALAPPDATA%\Transcribator\gui_crash.log`. |
| Очень долго без сегментов | Длинный фрагмент речи, CPU, тяжёлая модель; при зависании часами — VAD и логика `condition_on_previous_text` (см. выше); при необходимости `TRANSCRIBATOR_MAX_TRANSCRIBE_SECONDS`. |
| Окно закрылось | `gui_crash.log`; запуск `.\.venv\Scripts\python.exe -m transcribator.gui` из консоли для traceback. |
| ffmpeg не найден | `ffmpeg` в PATH; для видео и `.ogg`/`.oga` обязателен. |

---

**Последнее обновление:** 2026-04-09
