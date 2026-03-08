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

---

**Последнее обновление:** 2026-03-08
