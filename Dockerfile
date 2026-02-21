FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config.yaml .

# Create runtime directories
RUN mkdir -p data reports logs

CMD ["python", "-m", "src.main"]
