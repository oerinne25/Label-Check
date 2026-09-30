FROM python:3.12-slim

# Tesseract OCR engine (English model) + fonts used to render the sample labels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Build the sample labels into the image so "Try an example" and the sample zip work.
RUN python samples/generate_samples.py

# Tesseract itself is multi-threaded; keep one OCR thread per request so
# concurrent batch requests don't fight over CPU cores.
# WEB_CONCURRENCY = gunicorn worker count; 2 fits a 512 MB instance. Raise it on bigger hosts.
ENV OMP_THREAD_LIMIT=1 \
    PORT=8000 \
    WEB_CONCURRENCY=2
EXPOSE 8000
CMD gunicorn --bind 0.0.0.0:${PORT} --timeout 60 app:app
