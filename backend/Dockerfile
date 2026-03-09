# P&ID Backend: FastAPI + pipeline + LangChain/Gemini
FROM python:3.11-slim-bookworm

WORKDIR /app

# System deps for OpenCV, Tesseract, PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Backend requirements (build context = project root)
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir seaborn

# Pipeline and YOLO (all under backend/)
COPY backend/pid_graph /app/pid_graph
COPY backend/yolov5 /app/yolov5
COPY backend/weights /app/weights
COPY backend/app /app/app

# PYTHONPATH so pid_graph resolves to /app/pid_graph; ROOT_DIR in pid_graph = /app
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
