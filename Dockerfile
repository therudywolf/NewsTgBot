FROM python:3.11-slim

# Установка рабочей директории
WORKDIR /app

# Install system dependencies for Playwright
# Note: libgdk-pixbuf2.0-0 was replaced with libgdk-pixbuf-xlib-2.0-0 in newer Debian
# But Playwright's --with-deps handles most dependencies automatically
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libnss3 \
    libfontconfig1 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm-dev \
    libasound2 \
    wget \
    gnupg \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Копирование файла зависимостей
COPY requirements.txt .

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (run after pip install playwright)
RUN python -m playwright install chromium --with-deps 2>&1 || (echo "Warning: Playwright browser installation failed or playwright not installed" && true)

# Копирование кода приложения
COPY . .

# Создание директории для данных (если нужно)
RUN mkdir -p /app/data

# Указание точки входа
CMD ["python", "bot.py"]

