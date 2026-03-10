FROM python:3.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Force Python to use UTF-8 for all I/O (fixes UnicodeEncodeError in Docker containers)
ENV PYTHONUTF8=1
ENV PYTHONIOENCODING=utf-8

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config.yaml .

# Create runtime directories
RUN mkdir -p data reports logs

CMD ["python", "-m", "src.main"]
