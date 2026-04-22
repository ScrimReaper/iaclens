"""
Generate an interactive vis.js HTML graph report.

Features:
  - Node color by community
  - Node size by degree
  - Type filter checkboxes
  - Click node → details panel
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

_PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
]

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>infra-graph: {title}</title>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0d1117; color: #c9d1d9; display: flex; flex-direction: column;
            height: 100vh; overflow: hidden; }}
    #header {{ background: #161b22; padding: 10px 20px; border-bottom: 1px solid #30363d;
               display: flex; align-items: center; gap: 20px; flex-shrink: 0; }}
    #header h1 {{ font-size: 16px; color: #58a6ff; }}
    #header .stats {{ font-size: 12px; color: #8b949e; }}
    #main {{ display: flex; flex: 1; overflow: hidden; }}
    #sidebar {{ width: 260px; background: #161b22; border-right: 1px solid #30363d;
                display: flex; flex-direction: column; overflow: hidden; flex-shrink: 0; }}
    #filters {{ padding: 12px; border-bottom: 1px solid #30363d; overflow-y: auto; max-height: 200px; }}
    #filters h3 {{ font-size: 12px; color: #8b949e; margin-bottom: 8px; text-transform: uppercase; }}
    .filter-item {{ display: flex; align-items: center; gap: 6px; margin-bottom: 4px;
                    font-size: 12px; cursor: pointer; }}
    .filter-item input {{ cursor: pointer; }}
    .type-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
    #details {{ flex: 1; padding: 12px; overflow-y: auto; }}
    #details h3 {{ font-size: 12px; color: #8b949e; text-transform: uppercase; margin-bottom: 8px; }}
    #details-content {{ font-size: 12px; line-height: 1.6; }}
    .detail-field {{ margin-bottom: 6px; }}
    .detail-label {{ color: #8b949e; font-size: 11px; }}
    .detail-value {{ color: #c9d1d9; word-break: break-all; }}
    .edge-item {{ background: #21262d; border-radius: 4px; padding: 4px 6px;
                  margin-bottom: 3px; font-size: 11px; }}
    .edge-type {{ color: #58a6ff; }}
    #graph {{ flex: 1; }}
    #search-bar {{ padding: 8px 12px; border-bottom: 1px solid #30363d; }}
    #search-bar input {{ width: 100%; background: #21262d; border: 1px solid #30363d;
                         color: #c9d1d9; padding: 4px 8px; border-radius: 4px; font-size: 12px; }}
  </style>
</head>
<body>
  <div id="header">
    <h1>infra-graph</h1>
    <span class="stats">{node_count} nodes &bull; {edge_count} edges &bull; {community_count} communities</span>
  </div>
  <div id="main">
    <div id="sidebar">
      <div id="search-bar">
        <input type="text" id="search-input" placeholder="Search nodes..."/>
      </div>
      <div id="filters">
        <h3>Node Types</h3>
        <div id="type-filters"></div>
      </div>
      <div id="details">
        <h3>Details</h3>
        <div id="details-content">
          <span style="color:#8b949e;font-size:12px">Click a node to see details.</span>
        </div>
      </div>
    </div>
    <div id="graph"></div>
  </div>

  <script>
const NODES_DATA = {nodes_json};
const EDGES_DATA = {edges_json};
const NODE_MAP = {{}};
NODES_DATA.forEach(n => NODE_MAP[n.id] = n);

const COMMUNITY_COLORS = {community_colors};
const TYPE_COLORS = {type_colors};

// Build vis datasets
const visNodes = new vis.DataSet(NODES_DATA.map(n => ({{
  id: n.id,
  label: n.name || n.id.split("/").pop(),
  title: n.id,
  color: {{
    background: COMMUNITY_COLORS[n.community_id] || "#555",
    border: "#0d1117",
    highlight: {{ background: "#fff", border: "#58a6ff" }},
  }},
  size: Math.max(8, Math.min(30, 8 + n.degree * 2)),
  font: {{ color: "#c9d1d9", size: 11 }},
  _type: n.type,
  _hidden: false,
}})));

const visEdges = new vis.DataSet(EDGES_DATA.map(e => ({{
  from: e.from,
  to: e.to,
  label: e.type,
  arrows: "to",
  color: {{ color: "#30363d", highlight: "#58a6ff" }},
  font: {{ color: "#8b949e", size: 9, align: "middle" }},
  width: e.confidence < 0.8 ? 1 : 1.5,
  dashes: e.provenance === "AMBIGUOUS" || e.provenance === "INFERRED",
}})));

const container = document.getElementById("graph");
const network = new vis.Network(container, {{ nodes: visNodes, edges: visEdges }}, {{
  layout: {{ improvedLayout: true }},
  physics: {{
    enabled: true,
    barnesHut: {{ gravitationalConstant: -8000, springLength: 100, damping: 0.5 }},
    stabilization: {{ iterations: 150 }},
  }},
  interaction: {{ hover: true, tooltipDelay: 200 }},
}});

// Details panel
network.on("click", params => {{
  if (params.nodes.length === 0) return;
  const nodeId = params.nodes[0];
  const node = NODE_MAP[nodeId];
  if (!node) return;

  // Find edges
  const outE = EDGES_DATA.filter(e => e.from === nodeId);
  const inE = EDGES_DATA.filter(e => e.to === nodeId);

  let html = `
    <div class="detail-field">
      <div class="detail-label">ID</div>
      <div class="detail-value" style="color:#58a6ff">${{nodeId}}</div>
    </div>
    <div class="detail-field">
      <div class="detail-label">Type / Kind</div>
      <div class="detail-value">${{node.type}} / ${{node.kind}}</div>
    </div>
    <div class="detail-field">
      <div class="detail-label">Community</div>
      <div class="detail-value">${{node.community_id}}</div>
    </div>
    <div class="detail-field">
      <div class="detail-label">File</div>
      <div class="detail-value">${{node.file || "—"}}</div>
    </div>
    <div class="detail-field">
      <div class="detail-label">Degree</div>
      <div class="detail-value">${{node.degree}}</div>
    </div>
  `;
  if (outE.length) {{
    html += `<div class="detail-label" style="margin-top:8px">Outgoing edges (${{outE.length}})</div>`;
    outE.slice(0,8).forEach(e => {{
      html += `<div class="edge-item">→ <span class="edge-type">${{e.type}}</span> ${{e.to}}</div>`;
    }});
  }}
  if (inE.length) {{
    html += `<div class="detail-label" style="margin-top:8px">Incoming edges (${{inE.length}})</div>`;
    inE.slice(0,8).forEach(e => {{
      html += `<div class="edge-item">← <span class="edge-type">${{e.type}}</span> ${{e.from}}</div>`;
    }});
  }}
  document.getElementById("details-content").innerHTML = html;
}});

// Type filter checkboxes
const types = [...new Set(NODES_DATA.map(n => n.type))].sort();
const filterContainer = document.getElementById("type-filters");
const activeTypes = new Set(types);

types.forEach(t => {{
  const color = TYPE_COLORS[t] || "#888";
  const div = document.createElement("div");
  div.className = "filter-item";
  div.innerHTML = `
    <input type="checkbox" checked id="type-${{t}}" value="${{t}}"/>
    <span class="type-dot" style="background:${{color}}"></span>
    <label for="type-${{t}}">${{t}}</label>
  `;
  div.querySelector("input").addEventListener("change", e => {{
    if (e.target.checked) activeTypes.add(t);
    else activeTypes.delete(t);
    applyFilters();
  }});
  filterContainer.appendChild(div);
}});

function applyFilters() {{
  const searchVal = document.getElementById("search-input").value.toLowerCase();
  visNodes.forEach(n => {{
    const hidden = !activeTypes.has(n._type) ||
                   (searchVal && !n.id.toLowerCase().includes(searchVal) &&
                    !(n.label || "").toLowerCase().includes(searchVal));
    visNodes.update({{ id: n.id, hidden }});
  }});
}}

document.getElementById("search-input").addEventListener("input", applyFilters);
  </script>
</body>
</html>
"""


def generate_html(graph: nx.DiGraph, out_dir: Path, title: str = "Infrastructure Graph") -> Path:
    """
    Generate graph.html with inline vis.js visualization.

    Returns the path to the generated file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "graph.html"

    # Collect unique community IDs and types
    community_ids: set[int] = set()
    type_set: set[str] = set()
    for _, attrs in graph.nodes(data=True):
        cid = attrs.get("community_id", 0) or 0
        community_ids.add(cid)
        type_set.add(attrs.get("type", "unknown"))

    community_colors = {
        cid: _PALETTE[i % len(_PALETTE)]
        for i, cid in enumerate(sorted(community_ids))
    }
    type_colors = {
        t: _PALETTE[i % len(_PALETTE)]
        for i, t in enumerate(sorted(type_set))
    }

    # Build node list
    nodes: list[dict] = []
    for nid, attrs in graph.nodes(data=True):
        nodes.append(
            {
                "id": nid,
                "name": attrs.get("name") or nid.split("/")[-1],
                "type": attrs.get("type", "unknown"),
                "kind": attrs.get("kind", ""),
                "file": attrs.get("file") or "",
                "community_id": attrs.get("community_id", 0) or 0,
                "degree": graph.degree(nid),
                "line": attrs.get("line"),
                "labels": attrs.get("labels") or {},
            }
        )

    # Build edge list
    edges: list[dict] = []
    for frm, to, data in graph.edges(data=True):
        edges.append(
            {
                "from": frm,
                "to": to,
                "type": data.get("type", ""),
                "confidence": data.get("confidence", 1.0),
                "provenance": data.get("provenance", "EXTRACTED"),
            }
        )

    html = _HTML_TEMPLATE.format(
        title=title,
        node_count=len(nodes),
        edge_count=len(edges),
        community_count=len(community_ids),
        nodes_json=json.dumps(nodes, default=str),
        edges_json=json.dumps(edges, default=str),
        community_colors=json.dumps(community_colors),
        type_colors=json.dumps(type_colors),
    )

    html_path.write_text(html, encoding="utf-8")
    return html_path
