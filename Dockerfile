FROM python:3.11-slim

# Установка рабочей директории
WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Копирование файла зависимостей
COPY requirements.txt .

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (if playwright is installed)
RUN python -c "import playwright; playwright.install()" 2>/dev/null || true

# Копирование кода приложения
COPY . .

# Создание директории для данных (если нужно)
RUN mkdir -p /app/data

# Указание точки входа
CMD ["python", "bot.py"]

