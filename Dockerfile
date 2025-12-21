FROM python:3.11-slim

# Установка рабочей директории
WORKDIR /app

# Копирование файла зависимостей
COPY requirements.txt .

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY . .

# Создание директории для данных (если нужно)
RUN mkdir -p /app/data

# Указание точки входа
CMD ["python", "bot.py"]

