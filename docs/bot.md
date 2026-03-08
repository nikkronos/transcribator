# Telegram-бот Transcribator

В этом репозитории есть бот для Telegram: пользователь пересылает или отправляет голосовое сообщение — бот присылает текст (расшифровка, русский).

## Статус

**Сейчас бот отключён** (не запущен на сервере). Код и инструкции ниже — для повторного включения при необходимости. Чтобы остановить и отключить автозапуск на сервере: `systemctl stop transcribator-bot` и `systemctl disable transcribator-bot`. Чтобы снова включить: `systemctl enable transcribator-bot` и `systemctl start transcribator-bot`.

## Поведение

- **Команда /start** — приветствие и краткая инструкция.
- **Голосовое сообщение** — бот отвечает «Обрабатываю…», затем присылает распознанный текст (одним сообщением). Голосовые дольше 20 минут отклоняются.
- **Любое другое сообщение** — подсказка отправить голосовое.

Ответ только текстом, без файлов .txt/.json.

## Требования на сервере

- Python 3.10+
- ffmpeg в PATH (для конвертации голосовых .oga)
- Достаточно RAM для модели Whisper (по умолчанию `small`, ~500 MB)
- Токен бота от [@BotFather](https://t.me/BotFather)

## Переменные окружения

| Переменная | Обязательно | Описание |
|------------|-------------|----------|
| `TRANSCRIBATOR_BOT_TOKEN` или `BOT_TOKEN` | Да | Токен Telegram-бота |
| `TRANSCRIBATOR_BOT_MODEL` | Нет | Модель Whisper: tiny, base, small, medium, large-v3 (по умолчанию: small) |

## Установка и запуск на сервере

1. Клонировать репозиторий, перейти в папку проекта.
2. Создать venv и установить зависимости:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Linux
   pip install -r requirements.txt
   ```
3. Установить ffmpeg (если ещё нет): `apt install ffmpeg` (Debian/Ubuntu) или аналог.
4. Задать токен и запустить:
   ```bash
   export TRANSCRIBATOR_BOT_TOKEN="123456:ABC..."
   python -m transcribator.bot
   ```

### Запуск 24/7 (systemd)

1. Создать файл с токеном (не в репозитории):
   ```bash
   sudo nano /etc/systemd/system/transcribator-bot.env
   ```
   Одна строка: `TRANSCRIBATOR_BOT_TOKEN=твой_токен`

2. Скопировать пример юнита и подставить свои пути и пользователя:
   ```bash
   sudo cp docs/bot.service.example /etc/systemd/system/transcribator-bot.service
   sudo nano /etc/systemd/system/transcribator-bot.service
   ```
   Заменить `YOUR_USER` и пути ` /home/YOUR_USER/transcribator` на реальные (папка, куда клонирован репо, и пользователь под которым крутится сервис).

3. Включить и запустить:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable transcribator-bot
   sudo systemctl start transcribator-bot
   sudo systemctl status transcribator-bot
   ```
   Логи: `journalctl -u transcribator-bot -f`

## Репозиторий

Бот входит в репозиторий **Transcribator** (десктопное приложение, CLI и бот — один репо, см. README и ROADMAP).
