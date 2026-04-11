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

---

**Последнее обновление:** 2026-04-09
