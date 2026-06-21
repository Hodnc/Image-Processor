FROM python:3.12-slim

# OpenCV runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ALPR ONNX models at build time so cold starts are fast
RUN python -c "\
from fast_alpr import ALPR; \
ALPR(detector_model='yolo-v9-t-384-license-plate-end2end', ocr_model='global-plates-mobile-vit-v2-model'); \
print('Models cached successfully.')"

COPY alpr_service/ alpr_service/

RUN mkdir -p /data/input /data/processed /data/logs

EXPOSE 8080

CMD ["python", "-m", "alpr_service.main"]
