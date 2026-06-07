# Резюме сессии 2026-06-04

## Контекст работы

`Запуск Transcribator.bat` перестал открывать GUI и показывал ошибку:
`did not find executable at 'C:\Python314\python.exe'`.

## Диагноз

- BAT-файл исправен и запускает `.venv\Scripts\pythonw.exe`.
- `.venv` был создан на Python 3.14.3 из `C:\Python314`.
- Базовый Python 3.14 был удалён, поэтому сохранившийся `.venv` не мог запуститься.
- Внутри `.venv` сохранились зависимости и бинарные модули `cp314`, включая
  `faster-whisper` и NVIDIA CUDA-пакеты. Переключение окружения на Python 3.13
  без полной пересборки было невозможно.
- FFmpeg, NVIDIA GPU/драйвер и Visual C++ Runtime были исправны.

## Выполнено

1. Установлен Python 3.14.5 строго в `C:\Python314`.
2. Проверен базовый Python и `tkinter`.
3. Проверено восстановленное окружение:
   - `.venv\Scripts\python.exe` запускается на Python 3.14.5;
   - `python -m pip check` — зависимости не повреждены;
   - импорты `faster_whisper`, `ctranslate2`, `av`, `numpy`, `aiogram`,
     `transcribator.gui` и `transcribator.core` успешны;
   - CTranslate2 обнаруживает одно CUDA-устройство.
4. Пользователь выполнил полный smoke-тест:
   - GUI открылся через BAT;
   - режим `AUTO` выбрал GPU;
   - один файл успешно транскрибирован;
   - очередь завершилась без ошибок.
5. В `docs/gui-and-gpu-windows.md` добавлена инструкция восстановления после
   удаления базового Python.

## Известный open loop

- Скрипты ручной активации `.venv\Scripts\activate*` содержат старый путь
  `Cursor_Projects\Projects\Transcribator`. Это не мешает BAT и прямому запуску
  `.venv\Scripts\python.exe`, но ручная активация окружения требует пересоздания
  `.venv` либо обновления сгенерированных activation-скриптов.

---

**Последнее обновление:** 2026-06-04
