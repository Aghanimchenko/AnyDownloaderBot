# Используем официальный образ Python
FROM python:3.10-slim

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Устанавливаем ffmpeg и другие необходимые утилиты
# Обновляем список пакетов и устанавливаем ffmpeg, git (может понадобиться для некоторых зависимостей)
# Чистим кэш apt для уменьшения размера образа
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Копируем файл с зависимостями Python
COPY requirements.txt .

# Устанавливаем зависимости Python
# --no-cache-dir чтобы не хранить кэш pip
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код бота в рабочую директорию
COPY . .

# Команда, которая будет выполняться при запуске контейнера
# Запускаем основной скрипт бота
CMD ["python", "bot.py"]