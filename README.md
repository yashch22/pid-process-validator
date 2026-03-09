# P&ID Detector

P&ID (Piping and Instrumentation Diagram) upload, graph extraction, SOP upload, and validation. Backend uses YOLOv5 for symbol detection, OCR, and LangChain/Gemini for SOP processing.

## Demo

https://github.com/user-attachments/assets/ee287c20-f397-4b9b-9f50-b0158a7c14e7

## Prerequisites

- **Docker & Docker Compose** (recommended), or:
- **Python 3.11+**, **Node.js 18+**, **PostgreSQL 15+**
- **GEMINI_API_KEY** — for SOP ingestion and validation ([Google AI Studio](https://aistudio.google.com/apikey))

---

## Quick Start (Docker)

```bash
# 1. Clone and enter project
git clone <repo-url>
cd p&id_detector

# 2. Create backend/.env from example
cp backend/.env.example backend/.env

# 3. Edit backend/.env — set your GEMINI_API_KEY
# GEMINI_API_KEY=your_actual_key_here

# 4. Download YOLO weights (see Weights section below)

# 5. Run everything
docker compose up -d
```

- **Frontend:** http://localhost:5173  
- **Backend API:** http://localhost:8000  
- **API docs:** http://localhost:8000/docs  

---

## Setup (Step by Step)

### 1. Clone the repository

```bash
git clone <repo-url>
cd p&id_detector
```

### 2. Environment configuration

```bash
# Copy the example env file
cp backend/.env.example backend/.env

# Edit backend/.env and set:
# - GEMINI_API_KEY (required for SOP/validate)
# - DATABASE_URL / DATABASE_URL_SYNC if not using defaults
# - Optional: PID_UPLOAD_DIR, SOP_UPLOAD_DIR, CHROMA_PERSIST_DIR, YOLO_WEIGHTS_PATH
```

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://piduser:pidpass@localhost:5432/pid_db` | Async DB URL |
| `DATABASE_URL_SYNC` | `postgresql://piduser:pidpass@localhost:5432/pid_db` | Sync DB URL |
| `GEMINI_API_KEY` | — | **Required** for SOP extraction and validation |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Gemini model name |
| `PID_UPLOAD_DIR` | `data/uploads/pid` | P&ID upload directory |
| `SOP_UPLOAD_DIR` | `data/uploads/sop` | SOP upload directory |
| `CHROMA_PERSIST_DIR` | `data/chroma` | ChromaDB persistence |
| `YOLO_WEIGHTS_PATH` | (default) | Override path to `best.pt` |

### 3. YOLO weights

Download `best.pt` from the [latest release](https://github.com/yashch22/pid-process-validator/releases) and place it in `backend/weights/`:

```bash
# Example: download and place (adjust URL to your release)
curl -L -o backend/weights/best.pt https://github.com/yashch22/pid-process-validator/releases/download/v0.1.0/best.pt
```

If missing, P&ID detection will fail.

### 4. Run with Docker (recommended)

```bash
# Optional: pass GEMINI_API_KEY for build/runtime
export GEMINI_API_KEY=your_key

docker compose up -d
```

- PostgreSQL runs on port **5433** (host) → 5432 (container)
- Backend reads `backend/.env` for `GEMINI_*` and other overrides

### 5. Run locally (no Docker)

**PostgreSQL** — start a database (e.g. Docker):

```bash
docker run -d -p 5432:5432 \
  -e POSTGRES_USER=piduser \
  -e POSTGRES_PASSWORD=pidpass \
  -e POSTGRES_DB=pid_db \
  postgres:15-alpine
```

**Backend:**

```bash
cd backend
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend** (separate terminal):

```bash
cd frontend
npm install
npm run dev
```

Frontend dev server runs on port **8080** (see `frontend/vite.config.ts`). It uses `VITE_API_URL` or defaults to `http://localhost:8000` for the backend.

---

## Project structure

```
├── backend/
│   ├── app/           # FastAPI app, API routes, DB, services
│   ├── pid_graph/     # P&ID → graph pipeline (detection, OCR, line tracing)
│   ├── yolov5/        # YOLOv5 inference
│   ├── weights/       # YOLO weights (best.pt)
│   ├── .env.example   # Copy to .env
│   └── requirements.txt
├── frontend/          # React + Vite + shadcn/ui
├── docker-compose.yml
└── README.md
```

---

## API overview

| Method | Path | Description |
|--------|------|-------------|
| POST | `/upload/pid` | Upload P&ID (PDF/image). Returns `{ pid_id }`. |
| GET | `/graph/{pidId}` | Get graph (nodes, edges) for a P&ID. |
| POST | `/upload/sop` | Upload SOP (.docx/.txt). Form: `file`, `pid_id`. |
| POST | `/validate/{pidId}` | Validate SOP vs P&ID graph. Returns `{ status, issues[] }`. |

---

## Troubleshooting

- **"GEMINI_API_KEY not set"** — Add it to `backend/.env`.
- **P&ID detection fails** — Ensure `backend/weights/best.pt` exists.
- **Database connection refused** — Check PostgreSQL is running and `DATABASE_URL` matches (host, port, credentials).
- **Frontend can't reach backend** — Set `VITE_API_URL` when building, or ensure backend is at `http://localhost:8000` in dev.
