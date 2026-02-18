# AnyDownloaderBot

Telegram-бот для скачивания видео по ссылке, быстрой обрезки фрагментов и отправки медиа обратно в чат.

## Что умеет

- Скачивает видео через `yt-dlp` из популярных источников.
- Обрезает ролики по таймкоду (например, `10-20`) через `ffmpeg`.
- Отправляет результат в Telegram с предпросмотром и стримингом.
- Поддерживает массовую обработку ссылок в сообщении/группе.
- Хранит и отдает «картинки-команды» (`/katz`, `/bezugla` и т.д.) через `images.json`.
- Автоматически чистит временные файлы в `downloads/`.

## Технологии

- Python 3.10+
- `python-telegram-bot`
- `yt-dlp`
- `ffmpeg`
- Docker

## Архитектура (кратко)

- Основной код: `bot.py`
- Временные загрузки: `downloads/`
- База image-команд: `images.json`
- Куки для сложных источников: `cookies.txt`

Важные параметры в коде:

- Лимит файла для Telegram: ~50 MB (`MAX_FILE_SIZE_BYTES`)
- Очистка временных файлов: каждые 10 минут
- TTL файлов: 15 минут

## Поддерживаемые домены

- `youtube.com`, `youtu.be`
- `tiktok.com`
- `instagram.com`
- `reddit.com`
- `twitch.tv`
- `x.com`, `twitter.com`
- `vk.com`
- `pin.it`, `pinterest.com`

## Команды бота

Пользовательские:

- `/start` — проверка, что бот запущен.
- Любая ссылка на видео — бот предложит:
  - `Скачать`
  - `Обрезать` (запросит диапазон вроде `10-20`)
- Команды-картинки (`/katz`, `/solonin` и т.д.) — берутся из `images.json` или локальных файлов (`.jpg/.png/.webp/...`).

Админские:

- `/addpic <name>` — сохранить фото как команду `/<name>`.
- `/removepic <name>` — удалить команду-картинку.
- `/screenshot` — отправить скриншот экрана (если установлен `pyautogui` и разрешен доступ к экрану).

## Быстрый старт (локально)

### 1) Установка зависимостей

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2) Установить ffmpeg

`ffmpeg` должен быть доступен в `PATH` или рядом с `bot.py` как `ffmpeg.exe`.

### 3) Настроить токен

Рекомендуется через переменную окружения:

```bash
# Windows PowerShell
$env:BOT_TOKEN="<your_token>"

# Linux/macOS
# export BOT_TOKEN="<your_token>"
```

### 4) Запуск

```bash
python bot.py
```

## Запуск в Docker

Сборка:

```bash
docker build -t obr-bot .
```

Запуск:

```bash
docker run -d --name obr-bot \
  -e BOT_TOKEN="<your_token>" \
  -v ${PWD}/downloads:/app/downloads \
  -v ${PWD}/images.json:/app/images.json \
  obr-bot
```

Для приватных/ограниченных источников можно дополнительно примонтировать `cookies.txt` в `/app/cookies.txt`.

## Безопасность перед публикацией

В текущем коде (`bot.py`) есть fallback с хардкодом `BOT_TOKEN`.

Что сделать перед выкладкой в GitHub:

1. Удалить токен из кода и оставить только чтение из env.
2. Перевыпустить токен бота через BotFather (если токен уже светился в репозитории).
3. Добавить `cookies.txt` в `.gitignore` и не коммитить реальные cookies.
4. Ограничить `ADMIN_IDS` и вынести их в конфиг/env.

## Структура проекта

```text
.
├─ bot.py
├─ Dockerfile
├─ requirements.txt
├─ images.json
├─ cookies.txt
├─ downloads/
└─ *.jpg, *.mov (локальные медиа для команд)
```

## Ограничения

- Telegram-лимит на размер отправляемого файла (~50 MB).
- Часть источников требует актуальные cookies/авторизацию.
- Качество и доступность зависят от ограничений платформ и `yt-dlp`.

## Лицензия

Добавьте `LICENSE` при публикации (например, MIT).
