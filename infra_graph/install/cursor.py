"""Install infra-graph for Cursor: write .cursor/rules/infra-graph.mdc"""

from __future__ import annotations

from pathlib import Path

_CURSOR_MDC = """\
---
description: Infrastructure graph tools for Cursor — always query the graph first.
globs:
  - "**/*.tf"
  - "**/*.yml"
  - "**/*.yaml"
alwaysApply: true
---

# infra-graph: Infrastructure Knowledge Graph

This project has an infrastructure knowledge graph built by **infra-graph**.
Before reading Terraform/Kubernetes/Compose/Actions files directly, use the
MCP tools to get structural context.

## Available Tools

- `infra-graph:get_minimal_context` — start here
- `infra-graph:get_blast_radius <node_id>` — impact of a change
- `infra-graph:query_graph <node_id>` — trace dependencies
- `infra-graph:get_resource_context <node_id>` — single resource deep-dive
- `infra-graph:get_architecture_overview` — community map
- `infra-graph:detect_changes <diff>` — risk-score a git diff
- `infra-graph:find_hub_nodes` — most critical resources
- `infra-graph:get_knowledge_gaps` — orphans and ambiguous refs
- `infra-graph:build_or_update_graph <path>` — rebuild graph
- `infra-graph:search_resources <query>` — keyword search

## Node ID Format

| Infrastructure | Format |
|----------------|--------|
| Terraform resource | `resource.<type>.<name>` |
| Terraform variable | `variable.<name>` |
| Kubernetes resource | `<Kind>/<namespace>/<name>` |
| Compose service | `service/<project>/<name>` |
| GitHub Actions job | `job/<workflow>/<job_key>` |
| Helm chart | `helm_chart/<name>` |
"""


def install(project_root: Path) -> dict[str, str]:
    """Write .cursor/rules/infra-graph.mdc."""
    project_root = project_root.resolve()
    rules_dir = project_root / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    mdc_path = rules_dir / "infra-graph.mdc"
    mdc_path.write_text(_CURSOR_MDC)

    return {str(mdc_path.relative_to(project_root)): "created"}
