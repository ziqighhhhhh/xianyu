FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FAP_HOST=0.0.0.0 \
    FAP_PORT=8000 \
    FAP_DATA_DIR=/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY fap ./fap
COPY web ./web
COPY serve.py run.py ./

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "serve.py"]
