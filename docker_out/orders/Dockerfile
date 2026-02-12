# Базовый образ (можно менять версию через настройки)
FROM python:3.10-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# 1. Сначала копируем и устанавливаем общие зависимости (чтобы использовать кэш Docker)
COPY global_requirements.txt .
RUN pip install --no-cache-dir -r global_requirements.txt

# 2. Если у сервиса есть свои личные зависимости — ставим их

COPY orders/requirements.txt ./local_requirements.txt
RUN pip install --no-cache-dir -r local_requirements.txt


# 3. Копируем код самого сервиса
# Мы копируем папку сервиса в /app/service_name
COPY orders /app/orders

# 4. Копируем общие модули (common), если они нужны
COPY common /app/common

# 5. Указываем переменную окружения, чтобы Python видел наши папки
ENV PYTHONPATH=/app

# Команда запуска (пока заглушка, позже сделаем умнее)
CMD ["python", "-m", "orders.views"]