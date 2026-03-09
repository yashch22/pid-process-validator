# YOLO weights

Place your P&ID symbol detection weights here:

- **best.pt** — used by default by `pid_graph` (see `config.py` → `WEIGHTS_DIR`).

If you already have `best.pt` from training (e.g. from `extras/`), it has been copied here. Otherwise add your `best.pt` and ensure the backend can read this directory (e.g. in Docker it is copied to `/app/weights`).
