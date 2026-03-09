"""
pid_graph — P&ID image to graph extraction pipeline.

Modules
-------
ingestion     : PDF / image loading and tiling
preprocessing : denoising, binarization, deskewing
detection     : symbol bounding-box detection (classical + YOLO adapter)
ocr           : text / label extraction (Tesseract + PaddleOCR adapter)
line_tracer   : pipe / line skeleton extraction
graph_builder : NetworkX graph assembly
sop_parser    : SOP .docx parsing and NLP
cross_ref     : graph ↔ SOP discrepancy engine
reporter      : JSON log + HTML report generation
pipeline      : end-to-end orchestrator
"""

__version__ = "1.0.0"
__author__  = "pid_graph"
