# P&ID Backend

API for P&ID upload → graph extraction and SOP upload → validation (Gemini + LangChain).

## API (matches frontend contract)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/upload/pid` | Upload P&ID (PDF/image). Returns `{ "pid_id": "..." }`. |
| GET | `/graph/{pidId}` | Get graph (nodes, edges) for a P&ID. |
| POST | `/upload/sop` | Upload SOP (.docx/.txt). Body: `file`, `pid_id` (form). |
| POST | `/validate/{pidId}` | Validate SOP vs P&ID graph. Returns `{ status, issues[] }`. |

## Layout (all under backend/)

- **app/** — FastAPI app, API routes, DB, services.
- **pid_graph/** — P&ID → graph pipeline (detection, OCR, line tracing).
- **yolov5/** — YOLOv5 inference code (used by pid_graph).
- **weights/** — YOLO weights (`best.pt`); put your trained weights here.

No dependency on `extras/`; everything runs from `backend/`.

## Run locally (no Docker)

1. **PostgreSQL** running (e.g. `docker run -d -p 5432:5432 -e POSTGRES_USER=piduser -e POSTGRES_PASSWORD=pidpass -e POSTGRES_DB=pid_db postgres:15-alpine`).

2. **Env** (optional): copy `backend/.env.example` to `backend/.env` and set `GEMINI_API_KEY`, paths.

3. **Install** (from repo root):
   ```bash
   cd backend && pip install -r requirements.txt
   ```

4. **Run** (backend root must be on PYTHONPATH so both `app` and `pid_graph` are found):
   ```bash
   cd backend && PYTHONPATH=. uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Upload a P&ID** (PDF or image) to get a `pid_id`, then GET `/graph/{pid_id}` and optionally upload SOP and POST `/validate/{pid_id}`.

## Run with Docker (backend + frontend)

From **project root**:

```bash
export GEMINI_API_KEY=your_key   # optional but needed for SOP/validate
docker compose up -d
```

- **Frontend (UI):** http://localhost:5173  
- **Backend API:** http://localhost:8000  
- **API docs:** http://localhost:8000/docs  
- Docs: http://localhost:8000/docs  

DB and uploads persist in Docker volumes. Weights are copied from `backend/weights/` into the image; to override at runtime, mount:

```yaml
volumes:
  - ./backend/weights:/app/weights:ro
```

## Env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://piduser:pidpass@localhost:5432/pid_db` | Async DB URL. |
| `DATABASE_URL_SYNC` | sync variant of above | For pipeline (sync). |
| `PID_UPLOAD_DIR` | `data/uploads/pid` | Where P&ID files are stored. |
| `SOP_UPLOAD_DIR` | `data/uploads/sop` | Where SOP files are stored. |
| `GEMINI_API_KEY` | - | Required for SOP extraction and validation. |
| `PID_GRAPH_ROOT` | (backend root) | Override only if running a different layout. |
