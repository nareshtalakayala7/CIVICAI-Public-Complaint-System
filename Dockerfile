FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements-postgres.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
