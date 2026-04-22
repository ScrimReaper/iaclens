"""Install infra-graph for OpenAI Codex / OpenCode: write AGENTS.md"""

from __future__ import annotations

from pathlib import Path

_AGENTS_MD_SECTION = """
## infra-graph: Infrastructure Knowledge Graph Tools

This repository has a pre-built infrastructure knowledge graph. Use the
`infra-graph` MCP server tools **before** reading Terraform or Kubernetes files.

### Setup

```bash
infra-graph serve  # starts MCP stdio server
```

### Tool Reference

| Tool | Description |
|------|-------------|
| `get_minimal_context` | Quick orientation — graph stats + top nodes |
| `get_blast_radius(node_id)` | BFS impact analysis |
| `query_graph(from_node, direction)` | Trace dependencies |
| `get_resource_context(node_id)` | Single resource deep-dive |
| `get_architecture_overview` | Community map + coupling warnings |
| `detect_changes(diff_text)` | Risk-score a git diff |
| `find_hub_nodes(top_n)` | Most critical resources |
| `get_knowledge_gaps` | Orphans and ambiguous references |
| `build_or_update_graph(path)` | Rebuild or update graph |
| `search_resources(query)` | Keyword search |

### Node ID Examples

- `resource.aws_instance.web_server`
- `Deployment/default/my-app`
- `service/myproject/api`
- `job/ci-pipeline/build`
"""


def install(project_root: Path) -> dict[str, str]:
    """Write or update AGENTS.md in the project root."""
    project_root = project_root.resolve()
    agents_md_path = project_root / "AGENTS.md"
    marker = "## infra-graph: Infrastructure Knowledge Graph Tools"

    if agents_md_path.exists():
        existing = agents_md_path.read_text()
        if marker in existing:
            return {"AGENTS.md": "already configured (skipped)"}
        with agents_md_path.open("a") as f:
            f.write(_AGENTS_MD_SECTION)
        return {"AGENTS.md": "updated"}
    else:
        agents_md_path.write_text("# Agent Instructions\n" + _AGENTS_MD_SECTION)
        return {"AGENTS.md": "created"}
