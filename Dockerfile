# 1. Берем готовый официальный мини-образ Python
FROM python:3.10-slim

# 2. Создаем рабочую папку внутри контейнера
WORKDIR /app

# 3. Копируем файлы нашего бота туда
COPY . .

# 4. Устанавливаем библиотеки
RUN pip install --no-cache-dir -r requirements.txt

# 5. Запускаем бота
CMD ["python", "bot.py"]