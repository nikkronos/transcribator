# Done list: Transcribator

## История выполненных задач

### 2026-03-07
- Создана структура проекта (ROADMAP, DONE_LIST, SESSION_SUMMARY).
- Спецификация MVP и agent-onboarding в docs/.
- Реализован MVP: пакет transcribator (core, cli, audio_utils), поддержка аудио и видео, вывод .txt и .json с таймкодами, CLI с несколькими файлами и опцией -o.
- README, requirements.txt, .gitignore. Готовность к отдельному репозиторию.

### 2026-03-08
- Десктопное окно (transcribator/gui.py, tkinter): выбор файлов, папка вывода, модель, лог. Запуск: python -m transcribator.gui. Файл «Запуск Transcribator.bat» для запуска без PowerShell.
- Telegram-бот (transcribator/bot.py, aiogram 3): голосовое → текст, только русский. Поддержка .oga в audio_utils. Добавлен aiogram в requirements.
- Документация: docs/bot.md, docs/bot.service.example, обновлены README, ROADMAP, agent-onboarding. В ROADMAP — пункт про ускорение длинных файлов (GPU / нарезка).
- Деплой бота на сервер (Ubuntu): systemd 24/7, после pip install aiogram бот запущен и работает.

### 2026-04-09
- **GPU на Windows:** pip `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`; модуль `transcribator/_win_cuda_dlls.py` + вызов из `transcribator/__init__.py` — `add_dll_directory` и префикс `PATH` для `site-packages\nvidia\*\bin` (исправление `cublas64_12.dll`).
- **GUI:** прогресс и ETA по текущему файлу и очереди; выбор устройства `auto`/`cuda`/`cpu`; preflight CUDA; heartbeat «без нового сегмента»; `join` воркера после завершения; `WorkerResult` при критической ошибке; `report_callback_exception` и лог `%LOCALAPPDATA%\Transcribator\gui_crash.log`; точка входа `main()`.
- **Ядро (core):** Silero VAD по умолчанию; логика `condition_on_previous_text` (снижение зависаний на длинных файлах); опционально `TRANSCRIBATOR_MAX_TRANSCRIBE_SECONDS` (изолированный процесс); явное `del model` + `gc.collect()` после файла; preflight в GUI с очисткой probe-модели.
- **Документация:** `docs/gui-and-gpu-windows.md`; обновлены README (требования, установка GPU, таблица доков, GUI), `docs/agent-onboarding.md`, комментарии в `requirements.txt`.

### 2026-04-23
- **Антивылет GUI при batch-обработке:** в `gui.py` каждый файл запускается через изолированный дочерний процесс (`transcribe_file(..., isolate_process=True)`), чтобы авария нативного инференса не закрывала окно приложения.
- **Ядро (core):** `transcribe_file(...)` расширен параметрами `isolate_process` и `max_transcribe_seconds`; добавлена явная обработка аварийного завершения дочернего процесса по `exit code`.
- **Удобный resume:** в GUI добавлен автопропуск файлов, если уже существуют оба результата (`.txt` и `.json`).
- **Таймаут для GUI:** добавлена env-переменная `TRANSCRIBATOR_GUI_FILE_TIMEOUT_SECONDS` (опциональный лимит на один файл).
- **Проверка:** пользователь подтвердил, что после изменений обработка очереди проходит без вылета окна.

### 2026-06-04
- **Восстановлен локальный запуск:** после удаления базового Python окружение `.venv` снова работает благодаря установке Python 3.14.5 строго в `C:\Python314`.
- **Проверены зависимости:** `pip check` без ошибок; импорты GUI, ядра, `faster-whisper`, CTranslate2 и NVIDIA CUDA-пакетов успешны; обнаружено одно CUDA-устройство.
- **Полный smoke-тест:** GUI открыт через BAT, режим `AUTO` выбрал GPU, тестовый файл успешно транскрибирован без ошибок.
- **Документация:** в `docs/gui-and-gpu-windows.md` добавлен сценарий восстановления при ошибке `did not find executable at 'C:\Python314\python.exe'`.

### 2026-06-18
- **Диаризация «кто говорит»:** новый модуль `transcribator/diarization.py` на `sherpa-onnx` (pyannote-сегментация + эмбеддинги TitaNet + кластеризация). Без torch и без HuggingFace-токена, считается на CPU; ONNX-модели (~46 МБ) скачиваются один раз в `%LOCALAPPDATA%\Transcribator\models`.
- **Ядро (core):** `transcribe_file(...)` расширен параметрами `diarize` / `num_speakers` / `diar_threshold` (проброс и в изолированный процесс); сегментам назначается спикер по максимуму перекрытия с речевыми отрезками; `.txt` группируется в читаемые реплики (`[mm:ss] Спикер N:`), в `.json` добавлены поля `diarization`, `num_speakers` и `speaker` у сегментов. При сбое диаризации — мягкий откат к тексту без спикеров.
- **Аудио:** `audio_utils.ensure_wav_16k_mono(...)` — гарантированный 16 кГц моно WAV для общего входа whisper + диаризатора.
- **CLI/GUI:** флаги `--diarize`, `--speakers N`, `--diar-threshold`; в GUI — галочка «Диаризация (кто говорит)». `requirements.txt`: добавлены `sherpa-onnx`, `numpy`.
- **Диагностика GPU (важно):** замер показал, что faster-whisper **работает на GPU** в текущем venv и быстрее CPU ~26× (30с аудио: GPU 0.62с против CPU 16.4с). Гипотеза «медленно, потому что не на GPU» не подтвердилась.
- **Проверка:** компиляция всех модулей; e2e-прогон с диаризацией на синтезированном 2-голосном диалоге (модели скачались, найдено 2 спикера, txt/json корректны); юнит-тест логики слияния/группировки/граничных случаев — все ассерты прошли; проверена обратная совместимость пути без диаризации. **Открытый loop:** валидация качества диаризации на реальном многоголосом созвоне — за Никитой.

---

**Последнее обновление:** 2026-06-18
