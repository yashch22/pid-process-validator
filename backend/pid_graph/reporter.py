"""
reporter.py — Generate JSON log and HTML report from pipeline results.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx

from pid_graph.config import ReportConfig
from pid_graph.graph_builder import graph_summary
from pid_graph.models import Detection, Discrepancy, LineSegment, SopStep

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON Report
# ---------------------------------------------------------------------------

def build_json_report(
    detections:     List[Detection],
    segments:       List[LineSegment],
    G:              nx.Graph,
    sop_steps:      List[SopStep],
    discrepancies:  List[Discrepancy],
    xref_summary:   Dict[str, Any],
    source_files:   Dict[str, str],
    run_id:         Optional[str] = None,
) -> Dict[str, Any]:
    """Build a comprehensive JSON-serialisable report dict."""
    run_id = run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    gs = graph_summary(G)

    return {
        "run_id":    run_id,
        "timestamp": datetime.now().isoformat(),
        "source_files": source_files,
        "pipeline_summary": {
            "detections":          len(detections),
            "line_segments":       len(segments),
            "ocr_labelled":        sum(1 for d in detections if d.label),
            "isa_tags_found":      sum(1 for d in detections if d.isa_tag),
            "sop_steps_parsed":    len(sop_steps),
        },
        "graph_summary":    gs,
        "xref_summary":     xref_summary,
        "discrepancies":    [d.to_dict() for d in discrepancies],
        "graph_nodes":      [
            {
                "node_id":      nid,
                "symbol_class": data.get("symbol_class"),
                "label":        data.get("label"),
                "isa_tag":      data.get("isa_tag"),
                "center":       (data.get("center_x"), data.get("center_y")),
                "confidence":   data.get("confidence"),
            }
            for nid, data in G.nodes(data=True)
        ],
        "graph_edges": [
            {
                "source":    u,
                "target":    v,
                "line_type": data.get("line_type"),
                "length_px": data.get("length_px"),
            }
            for u, v, data in G.edges(data=True)
        ],
    }


def save_json_report(report: Dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    log.info("JSON report → %s", path)
    return path


# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------

def build_html_report(
    report:         Dict[str, Any],
    annotated_img:  Optional[str] = None,
    graph_img:      Optional[str] = None,
    interactive_graph: Optional[str] = None,
) -> str:
    """Render a self-contained HTML report string."""
    disc_rows = _render_disc_rows(report.get("discrepancies", []))
    node_rows = _render_node_rows(report.get("graph_nodes", []))
    gs        = report.get("graph_summary", {})
    xs        = report.get("xref_summary", {})
    ps        = report.get("pipeline_summary", {})

    img_html = ""
    if annotated_img:
        img_html += f"""
        <div class="card">
          <h2>📐 Annotated P&ID</h2>
          <img src="{annotated_img}" style="max-width:100%;border-radius:8px;" />
        </div>"""
    if graph_img:
        img_html += f"""
        <div class="card">
          <h2>🕸️ Graph Visualisation</h2>
          <img src="{graph_img}" style="max-width:100%;border-radius:8px;" />
        </div>"""
    if interactive_graph:
        img_html += f"""
        <div class="card">
          <h2>🔍 Interactive Graph</h2>
          <iframe src="{interactive_graph}" width="100%" height="600px"
                  style="border:1px solid #ddd;border-radius:8px;"></iframe>
        </div>"""

    crit = xs.get("critical_count", 0)
    warn = xs.get("warning_count", 0)
    info = xs.get("info_count", 0)
    total_disc = xs.get("total_discrepancies", 0)
    coverage   = xs.get("coverage_pct", 0)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>P&ID Analysis Report — {report.get('run_id','')}</title>
<style>
  :root {{
    --blue: #1a4a6e; --accent: #2563eb; --green: #10b981;
    --orange: #f59e0b; --red: #ef4444; --gray: #f1f5f9;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f8fafc;
          color: #1e293b; line-height: 1.6; }}
  .header {{
    background: linear-gradient(135deg, #0f2d4a, #1a4a6e);
    color: white; padding: 40px 48px;
  }}
  .header h1 {{ font-size: 28px; font-weight: 800; margin-bottom: 6px; }}
  .header p  {{ color: rgba(255,255,255,0.65); font-size: 14px; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 40px; }}
  .stats-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px; margin-bottom: 32px;
  }}
  .stat {{
    background: white; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 20px 22px;
  }}
  .stat-value {{ font-size: 32px; font-weight: 800; color: var(--accent); }}
  .stat-label {{ font-size: 12px; color: #64748b; text-transform: uppercase;
                 letter-spacing: 1px; margin-top: 4px; }}
  .card {{
    background: white; border: 1px solid #e2e8f0; border-radius: 14px;
    padding: 28px 32px; margin-bottom: 24px;
  }}
  .card h2 {{ font-size: 18px; font-weight: 700; margin-bottom: 18px;
              color: var(--blue); border-bottom: 2px solid #e2e8f0;
              padding-bottom: 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #0f2d4a; color: white; padding: 10px 14px;
        text-align: left; font-size: 12px; }}
  td {{ padding: 10px 14px; border-bottom: 1px solid #f1f5f9;
        vertical-align: top; }}
  tr:hover td {{ background: #f8fafc; }}
  .badge {{
    display: inline-block; padding: 3px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 700;
  }}
  .CRITICAL {{ background: #fee2e2; color: #991b1b; }}
  .WARNING  {{ background: #fef3c7; color: #92400e; }}
  .INFO     {{ background: #dbeafe; color: #1e40af; }}
  .progress-bar-wrap {{
    background: #e2e8f0; border-radius: 20px; height: 20px; overflow: hidden;
    margin: 8px 0;
  }}
  .progress-bar {{
    height: 100%; border-radius: 20px;
    background: linear-gradient(90deg, #10b981, #2563eb);
    display: flex; align-items: center; padding-left: 10px;
    color: white; font-size: 12px; font-weight: 700;
    transition: width 0.5s;
  }}
  .footer {{
    text-align: center; color: #94a3b8; font-size: 12px;
    padding: 24px 0;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>🔧 P&ID Analysis Report</h1>
  <p>Run ID: {report.get('run_id','')} &nbsp;·&nbsp;
     {report.get('timestamp','')[:19]} &nbsp;·&nbsp;
     Source: {list(report.get('source_files',{}).values())[0] if report.get('source_files') else 'N/A'}</p>
</div>

<div class="container">

  <div class="stats-grid">
    <div class="stat">
      <div class="stat-value">{gs.get('node_count',0)}</div>
      <div class="stat-label">Graph Nodes</div>
    </div>
    <div class="stat">
      <div class="stat-value">{gs.get('edge_count',0)}</div>
      <div class="stat-label">Graph Edges</div>
    </div>
    <div class="stat">
      <div class="stat-value">{ps.get('detections',0)}</div>
      <div class="stat-label">Symbols Detected</div>
    </div>
    <div class="stat">
      <div class="stat-value">{ps.get('isa_tags_found',0)}</div>
      <div class="stat-label">ISA Tags Found</div>
    </div>
    <div class="stat">
      <div class="stat-value" style="color:{'#ef4444' if crit > 0 else '#10b981'}">{crit}</div>
      <div class="stat-label">Critical Issues</div>
    </div>
    <div class="stat">
      <div class="stat-value" style="color:#f59e0b">{warn}</div>
      <div class="stat-label">Warnings</div>
    </div>
    <div class="stat">
      <div class="stat-value">{coverage}%</div>
      <div class="stat-label">SOP Coverage</div>
    </div>
    <div class="stat">
      <div class="stat-value">{xs.get('total_sop_tags',0)}</div>
      <div class="stat-label">SOP Tags Total</div>
    </div>
  </div>

  <!-- SOP Coverage Progress -->
  <div class="card">
    <h2>📊 SOP Tag Coverage</h2>
    <div class="progress-bar-wrap">
      <div class="progress-bar" style="width:{min(coverage,100)}%">
        {coverage}%
      </div>
    </div>
    <p style="font-size:13px;color:#4b5563;margin-top:8px;">
      {xs.get('matched_tags',0)} of {xs.get('total_sop_tags',0)} SOP tags found in P&ID graph.
      {xs.get('missing_tags',0)} missing.
      Discrepancies: {crit} critical, {warn} warnings, {info} info.
    </p>
  </div>

  {img_html}

  <!-- Discrepancy Table -->
  <div class="card">
    <h2>⚠️ Discrepancies ({total_disc})</h2>
    {'<p style="color:#10b981;font-weight:600;">✅ No discrepancies found.</p>' if total_disc == 0 else ''}
    {'<table><thead><tr><th>ID</th><th>Severity</th><th>Type</th><th>SOP Tag</th><th>Graph Tag</th><th>Message</th><th>Action</th></tr></thead><tbody>' + disc_rows + '</tbody></table>' if total_disc > 0 else ''}
  </div>

  <!-- Component Table -->
  <div class="card">
    <h2>🔩 Detected Components ({len(report.get('graph_nodes',[]))})</h2>
    <table>
      <thead>
        <tr><th>Node ID</th><th>Class</th><th>ISA Tag</th><th>Label</th><th>Confidence</th></tr>
      </thead>
      <tbody>{node_rows}</tbody>
    </table>
  </div>

  <!-- Graph Summary -->
  <div class="card">
    <h2>📈 Graph Statistics</h2>
    <table>
      <thead><tr><th>Metric</th><th>Value</th></tr></thead>
      <tbody>
        <tr><td>Nodes</td><td>{gs.get('node_count',0)}</td></tr>
        <tr><td>Edges</td><td>{gs.get('edge_count',0)}</td></tr>
        <tr><td>Connected Components</td><td>{gs.get('component_count',0)}</td></tr>
        <tr><td>Average Degree</td><td>{gs.get('avg_degree',0)}</td></tr>
        <tr><td>Labelled Nodes</td><td>{gs.get('labelled_nodes',0)}</td></tr>
        <tr><td>ISA-Tagged Nodes</td><td>{gs.get('tagged_nodes',0)}</td></tr>
      </tbody>
    </table>
    <div style="margin-top:16px;">
      <strong style="font-size:13px;">Component Type Distribution:</strong>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;">
        {"".join(f'<span style="background:#dbeafe;color:#1e40af;padding:3px 10px;border-radius:12px;font-size:12px;">{cls.replace("_"," ")} ×{cnt}</span>' for cls, cnt in sorted(gs.get("component_types",{}).items(), key=lambda x:-x[1])[:15])}
      </div>
    </div>
  </div>

</div>

<div class="footer">
  Generated by pid_graph pipeline · {report.get('timestamp','')[:10]}
</div>

</body>
</html>"""
    return html


def save_html_report(html: str, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("HTML report → %s", path)
    return path


# ---------------------------------------------------------------------------
# Table renderers
# ---------------------------------------------------------------------------

def _render_disc_rows(discrepancies: List[Dict]) -> str:
    rows = []
    for d in discrepancies:
        sev = d.get("severity", "INFO")
        rows.append(
            f"<tr>"
            f"<td>{d.get('disc_id','')}</td>"
            f"<td><span class='badge {sev}'>{sev}</span></td>"
            f"<td>{d.get('type','').replace('_',' ')}</td>"
            f"<td><code>{d.get('sop_tag') or ''}</code></td>"
            f"<td><code>{d.get('graph_tag') or ''}</code></td>"
            f"<td style='max-width:320px'>{d.get('message','')}</td>"
            f"<td style='max-width:200px;color:#4b5563'>{d.get('suggested_action','')}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _render_node_rows(nodes: List[Dict]) -> str:
    rows = []
    for n in nodes[:200]:   # cap at 200 for large diagrams
        conf = n.get("confidence", 0) or 0
        rows.append(
            f"<tr>"
            f"<td><code>{n.get('node_id','')}</code></td>"
            f"<td>{str(n.get('symbol_class','')).replace('_',' ')}</td>"
            f"<td><code>{n.get('isa_tag') or '—'}</code></td>"
            f"<td>{n.get('label') or '—'}</td>"
            f"<td>{conf:.2f}</td>"
            f"</tr>"
        )
    return "\n".join(rows)
