# pid_graph

P&ID image/PDF → NetworkX graph pipeline (symbol detection, OCR, line tracing).

Lives under **backend/** so the API and pipeline are in one place.

- **Config**: `config.py` — `ROOT_DIR` = parent of this package (= backend root). Weights at `ROOT_DIR/weights/best.pt`, YOLOv5 at `ROOT_DIR/yolov5/`.
- **Entry**: `pipeline.py` — `Pipeline(cfg).run(path)` returns graph, detections, etc.
- **Backend use**: `app.services.pid_service.run_pipeline(path)` runs this and returns API-format graph.

Weights and yolov5 are siblings of this package under backend (see backend/README.md).
