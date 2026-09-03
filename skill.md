# iaclens Skill

## Trigger

`/iaclens`

## What it does

Builds or updates the infrastructure knowledge graph for the current project,
then returns a concise summary of the graph structure to orient the assistant.

After building, it invokes the MCP tools to provide:
1. A minimal context summary (god nodes, community count)
2. An architecture overview (community map, coupling warnings)
3. Suggested questions about the infrastructure

## Workflow

When the user types `/iaclens`:

1. **Build or update the graph**
   ```bash
   iaclens build . --update
   ```
   Or, if the graph has never been built:
   ```bash
   iaclens build .
   ```

2. **Get orientation** using MCP tools (in order):
   - Call `get_minimal_context` → understand scale and top nodes
   - Call `get_architecture_overview` → community map and coupling warnings
   - Call `find_hub_nodes` → identify critical resources

3. **Report back** with:
   - Node/edge counts and file types parsed
   - Top 3-5 "god nodes" (highest degree)
   - Community summary (how many, what types dominate each)
   - Any coupling warnings
   - 3-5 suggested questions about the infrastructure

## MCP Tool Reference

| Tool | When to use |
|------|-------------|
| `get_minimal_context` | Quick orientation after build |
| `get_blast_radius(node_id, max_depth)` | Impact analysis — "what breaks if X changes?" |
| `query_graph(from_node, direction)` | Trace dependencies from any node |
| `get_resource_context(node_id)` | Deep-dive on one resource |
| `get_architecture_overview` | Full community map |
| `detect_changes(diff_text)` | Risk-score a git diff before review |
| `find_hub_nodes(top_n)` | Most critical / risky resources |
| `get_knowledge_gaps` | Orphaned resources, unresolved refs |
| `build_or_update_graph(path)` | Rebuild from within assistant |
| `search_resources(query)` | Keyword search across all nodes |

## Node ID Format

| Infrastructure type | Node ID format |
|--------------------|----------------|
| Terraform resource | `resource.<type>.<name>` |
| Terraform variable | `variable.<name>` |
| Terraform output | `output.<name>` |
| Terraform data | `data.<type>.<name>` |
| Terraform module | `module.<name>` |
| Kubernetes resource | `<Kind>/<namespace>/<name>` |
| Compose service | `service/<project>/<name>` |
| Compose volume | `volume/<project>/<name>` |
| GitHub Actions job | `job/<workflow>/<job_key>` |
| GitHub Actions step | `step/<workflow>/<job>/<index>` |
| Helm chart | `helm_chart/<name>` |
| Kustomize overlay | `kustomize/<name>` |

## Example usage

```
/iaclens

# After build, you might ask:
What is the blast radius if the aws_vpc.main resource changes?
→ Use: get_blast_radius("resource.aws_vpc.main", max_depth=5)

Which resources in the default namespace depend on the app-config ConfigMap?
→ Use: query_graph("ConfigMap/default/app-config", direction="upstream")

Show me the architecture overview for this project.
→ Use: get_architecture_overview()
```
