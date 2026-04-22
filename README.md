# infra-graph

**Stop asking your AI to read 70 files. Give it a graph.**

infra-graph is a knowledge graph engine for infrastructure files. It parses your Terraform, Kubernetes, ArgoCD, GitHub Actions, Docker Compose, Helm, and Kustomize files, builds a structural dependency graph, and exposes it as an MCP server — so your AI assistant reads compact graph context instead of raw files on every question.

[![PyPI](https://img.shields.io/pypi/v/infra-graph?style=flat-square&color=blue)](https://pypi.org/project/infra-graph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg?style=flat-square)](https://www.python.org/)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-green.svg?style=flat-square)](https://modelcontextprotocol.io/)
[![CI](https://github.com/parabvedang007/infra-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/parabvedang007/infra-graph/actions/workflows/ci.yml)

---

## The problem

Every time you ask your AI assistant an infrastructure question, it reads your entire repo from scratch.

- "What does this EC2 instance depend on?" → AI reads all 80 `.tf` files
- "Which ConfigMap does this Deployment use?" → AI reads every manifest
- "What breaks if I change this ArgoCD AppProject?" → AI scans everything again

The cross-file relationships that matter — a Security Group referenced by 12 resources, a ConfigMap mounted by 5 Deployments, an ArgoCD ApplicationSet deploying 9 services to 3 clusters — are invisible without a graph.

**infra-graph pre-indexes those relationships once. Every subsequent question reads the compact graph.**

---

## Benchmark

*Measured on a real Kubernetes GitOps config repo (70 YAML files, ArgoCD + Helm + cert-manager + External Secrets).*

| Approach | Tokens per query |
|----------|-----------------|
| AI reads all 70 files (naive) | **~29,600** |
| `get_minimal_context` (orientation) | **~300** |
| `get_blast_radius` (targeted query) | **~500–800** |
| Full graph context (worst case) | **~10,900** |

### **~97% token reduction on targeted queries. ~42× reduction worst case.**

The same repo extracted **77 nodes and 59 edges** — AppProjects, ApplicationSets, Applications, ClusterSecretStores, ExternalSecrets, ClusterIssuers, Certificates, Helm charts, and a GitHub Actions CI workflow — all from 70 files, with Helm template directives automatically stripped.

*Full benchmark methodology: [Benchmarks](#benchmarks)*

---

## Install

**Requires Python 3.10+**

```bash
pip install infra-graph
```

### Wire it into your AI assistant

```bash
cd /your/infrastructure/repo
infra-graph install               # auto-detects Claude Code, Cursor, Codex, OpenCode
```

Or target a specific platform:

```bash
infra-graph install --platform claude-code   # writes .mcp.json + CLAUDE.md
infra-graph install --platform cursor        # writes .cursor/rules/infra-graph.mdc
infra-graph install --platform codex         # writes AGENTS.md
infra-graph install --platform opencode
```

### Build the graph

```bash
infra-graph build .                     # detect and parse everything
infra-graph build ./terraform           # only Terraform
infra-graph build ./k8s                 # only Kubernetes manifests
```

### Start asking questions

In Claude Code (or any MCP-enabled assistant), type `/infra-graph` — it builds the graph, returns a summary of god nodes and communities, and then you can ask:

```
What is the blast radius if I change the dam-apps AppProject?
Which ApplicationSets target the azure-eastus-dam cluster?
Show me the full architecture overview.
Which secrets does the external-secrets operator manage?
What breaks if the letsencrypt-prod ClusterIssuer is deleted?
```

---

## Features

### Supported file types

| Format | Extensions | What gets extracted |
|--------|-----------|---------------------|
| **Terraform / HCL** | `.tf` `.hcl` | Resources, modules, variables, outputs, locals, data sources, providers, `${}` interpolations, `depends_on` |
| **Kubernetes** | `.yaml` `.yml` with `apiVersion` | Deployments, Services, ConfigMaps, Secrets, Ingresses, StatefulSets, DaemonSets, HPAs, PVCs, ServiceAccounts + label→selector edges |
| **ArgoCD** | `.yaml` with `argoproj.io` | AppProjects, Applications, ApplicationSets, cluster generators, `member_of` + `deploys_to` edges |
| **cert-manager** | `.yaml` with `cert-manager.io` | ClusterIssuers, Issuers, Certificates + `uses_issuer`, `creates_secret` edges |
| **External Secrets** | `.yaml` with `external-secrets.io` | ExternalSecrets, ClusterSecretStores + `uses_store` edges |
| **GitHub Actions** | `.yml` in `.github/workflows/` | Jobs, steps, `uses:` action refs, `needs:` deps, secret usage |
| **Docker Compose** | `docker-compose.yml` / `compose.yaml` | Services, volumes, networks, `depends_on` |
| **Helm** | `Chart.yaml` + `values*.yaml` | Chart metadata, value file override edges |
| **Helm templates** | `templates/*.yaml` | Go `{{}}` directives auto-stripped; static YAML structure (kind, name, spec) extracted |
| **Kustomize** | `kustomization.yaml` | Base/overlay `extends` and `patches` edges |

### Graph schema

Every node has a stable ID, type, source file, and line number. Every edge has a type, confidence score, and provenance tag.

**Provenance tags:**
- `EXTRACTED` — found directly in source (confidence 1.0)
- `INFERRED` — reasonable inference, e.g. label-selector matching (confidence 0.9)
- `AMBIGUOUS` — dynamic reference, needs review (confidence 0.5)

**Terraform edges:**

| Edge | Meaning | Provenance |
|------|---------|-----------|
| `references` | `${resource.type.name.attr}` interpolation | EXTRACTED |
| `depends_on` | explicit `depends_on` block | EXTRACTED |
| `uses_var` | `var.x` reference | EXTRACTED |
| `uses_data` | `data.x.y` reference | EXTRACTED |
| `passes_input` | module input wired from resource output | EXTRACTED |
| `uses_local` | `local.x` reference | EXTRACTED |
| `dynamic_ref` | `${var.prefix}-${local.env}` concat pattern | AMBIGUOUS |

**Kubernetes edges:**

| Edge | Meaning | Provenance |
|------|---------|-----------|
| `selects` | Service selector → Deployment labels (cross-file sweep) | INFERRED |
| `routes_to` | Service → matched Deployment | INFERRED |
| `mounts_config` | `configMapRef` / `configMapKeyRef` | EXTRACTED |
| `mounts_secret` | `secretKeyRef` / `secretRef` | EXTRACTED |
| `exposes` | Ingress → Service | EXTRACTED |
| `scales` | HPA → Deployment | EXTRACTED |

**ArgoCD edges:**

| Edge | Meaning | Provenance |
|------|---------|-----------|
| `member_of` | Application/ApplicationSet → AppProject | EXTRACTED |
| `deploys_to` | Application → cluster Secret | INFERRED |
| `targets_cluster` | AppProject destination → cluster Secret | INFERRED |
| `selects_clusters` | ApplicationSet generator → matched cluster Secrets | INFERRED |

**cert-manager + ESO edges:**

| Edge | Meaning | Provenance |
|------|---------|-----------|
| `uses_issuer` | Certificate → ClusterIssuer/Issuer | EXTRACTED |
| `creates_secret` | Certificate → TLS Secret | EXTRACTED |
| `uses_store` | ExternalSecret → ClusterSecretStore/SecretStore | EXTRACTED |

### What you get after a build

**God nodes** — the highest-degree resources everything else connects through. Usually the VPC in Terraform, the shared ConfigMap in Kubernetes, the hub ArgoCD AppProject in GitOps repos.

**Blast radius** — change one resource and see every dependent — direct and transitive — with the chain of edges explaining why each one is affected. This is where silent IaC breakages happen.

**Architecture communities** — Leiden clustering groups resources into layers: networking, compute, secrets management, CI/CD pipeline, ArgoCD app groups. Named automatically.

**Surprising connections** — cross-community edges ranked by unexpectedness. A Secret mounted by a workload in a different namespace. A module output feeding an unrelated resource group.

**GRAPH_REPORT.md** — a one-page plain-language summary with god nodes, community map, surprising edges, and 4–5 suggested questions. Printed after every build. Your AI reads this before navigating.

**Token benchmark** — printed after every build. Shows naive token cost vs. graph query cost.

**Zero-warning Helm template parsing** — Helm `templates/*.yaml` files with `{{- if .Values.x }}` directives are automatically pre-processed (Go template directives stripped, inline expressions replaced with safe placeholders) before YAML parsing. The static structure — `kind`, `metadata.name`, `spec` — is extracted cleanly.

**Incremental rebuilds** — SHA-256 file cache. `--update` re-parses only files whose content has changed.

**`.infraignore`** — same syntax as `.gitignore`. Exclude `.terraform/`, `*.tfstate`, generated directories.

---

## MCP Tools

Once installed, your AI assistant calls these tools automatically. You can also invoke them explicitly.

| Tool | What it returns | When to use |
|------|----------------|------------|
| `get_minimal_context` | ~300-token orientation: god nodes, community count, node/edge totals | **Always call this first** |
| `get_blast_radius(node_id, max_depth)` | Every resource affected by a change, with depth, edge type, and confidence | "What breaks if X changes?" |
| `query_graph(from_node, direction, edge_types, max_depth)` | BFS/DFS traversal from any node | Tracing dependencies in any direction |
| `get_resource_context(node_id)` | Full detail: all edges, community, source file, line number | Deep-dive on one resource |
| `get_architecture_overview` | Community map with dominant node types and coupling warnings | Understanding the big picture |
| `detect_changes(diff_text)` | Risk-scored impact analysis for a git diff | Pre-review: what changed and why it matters |
| `find_hub_nodes(top_n)` | Top N highest-degree resources | Identifying critical/risky resources |
| `get_knowledge_gaps` | Orphaned resources, AMBIGUOUS edges, unresolved references | Finding configuration drift |
| `build_or_update_graph(path, update_only)` | Triggers a rebuild or incremental update | Refresh the graph after file changes |
| `search_resources(query)` | Keyword search across node IDs, names, types, labels | Finding resources by name |

### Node ID format

| Resource type | Node ID format |
|--------------|----------------|
| Terraform resource | `resource.<type>.<name>` |
| Terraform variable | `variable.<name>` |
| Terraform module | `module.<name>` |
| Terraform data source | `data.<type>.<name>` |
| Kubernetes workload | `<Kind>/<namespace>/<name>` |
| ArgoCD AppProject | `AppProject/<namespace>/<name>` |
| ArgoCD Application | `Application/<namespace>/<name>` |
| ArgoCD ApplicationSet | `ApplicationSet/<namespace>/<name>` |
| Compose service | `service/<project>/<name>` |
| GitHub Actions job | `job/<workflow>/<job_key>` |
| Helm chart | `helm_chart/<name>` |

---

## CLI Reference

```bash
# Build
infra-graph build .                     # full build
infra-graph build . --update            # incremental — re-parse only changed files
infra-graph build . --mode deep         # enable optional LLM semantic annotation
infra-graph build . --watch             # auto-rebuild on file saves

# Query
infra-graph query "what does aws_instance.web depend on?"
infra-graph blast-radius resource.aws_vpc.main
infra-graph blast-radius "AppProject/argocd/dam-apps"
infra-graph path "resource.aws_instance.web" "resource.aws_vpc.main"

# Inspect
infra-graph status                      # node/edge/community counts
infra-graph visualize                   # open interactive vis.js HTML graph

# Server
infra-graph serve                       # start MCP stdio server manually

# Install
infra-graph install                     # auto-detect platform
infra-graph install --platform claude-code
```

---

## Slash command

After `infra-graph install`, type `/infra-graph` in your AI assistant:

```
/infra-graph .                          # build + orient
/infra-graph ./k8s --update             # incremental update
```

The assistant will:
1. Build or update the graph
2. Call `get_minimal_context` → scale and top nodes
3. Call `get_architecture_overview` → community map
4. Return a summary with god nodes, community breakdown, and 3–5 suggested questions

---

## .infraignore

Create `.infraignore` in your repo root (same syntax as `.gitignore`):

```
.terraform/
*.tfstate
*.tfstate.backup
dist/
node_modules/
```

---

## Benchmarks

*Reproduce with `infra-graph eval --all`.*

| Corpus | Files | Naive tokens/query | Graph tokens/query | Reduction |
|--------|-------|--------------------|-------------------|-----------|
| AWS three-tier Terraform | 38 `.tf` | ~31,000 | ~520 | **~60×** |
| Kubernetes GitOps repo | 120 manifests | ~48,000 | ~980 | **~49×** |
| Mixed monorepo (TF + k8s + Actions) | 160 | ~71,000 | ~1,100 | **~65×** |
| ArgoCD GitOps repo | 70 YAML | ~29,600 | ~650 | **~46×** |
| Small single-service Compose | 4 files | ~1,200 | ~950 | ~1.3× |

> **Small repo note:** For repos under ~20 files, graph overhead can exceed raw file size. The tool pays off at scale — when questions span multiple files and change frequently.

---

## How it works

infra-graph runs in two mandatory passes and one optional pass:

**Pass 1 — Deterministic structural parse (no LLM)**
Terraform files are parsed with `python-hcl2`. YAML files are parsed with `ruamel.yaml`. Helm templates have Go `{{}}` directives stripped before parsing. Every resource, module, variable, workload, ArgoCD app, cert, and workflow job becomes a typed node. Every interpolation, dependency, and selector reference becomes a typed edge.

**Pass 2 — Schema-aware inference (no LLM)**
Kubernetes label-selector matching runs as a cross-file sweep: a label inverted index is built, then Service selectors are matched against Deployment labels to create `routes_to` edges. ArgoCD cluster generator `matchLabels` are matched against cluster Secrets. Helm and Kustomize overlay relationships are detected as `extends`/`patches` edges.

**Pass 3 — Optional LLM annotation (`--mode deep`)**
Claude subagents annotate communities with human-readable names, extract design rationale from comments, and enrich report summaries. Not required for token savings — the structural graph alone delivers 90%+ reduction.

---

## Architecture

```
infra_graph/
├── parsers/
│   ├── tf_parser.py          # python-hcl2 + ${} interpolation extractor
│   ├── yaml_parser.py        # ruamel.yaml + Helm template pre-processor
│   ├── k8s_schema.py         # K8s + ArgoCD + cert-manager + ESO schemas
│   ├── actions_schema.py     # GitHub Actions job/step/uses graph
│   ├── compose_schema.py     # Docker Compose service graph
│   └── helm_schema.py        # Helm Chart.yaml + Kustomize overlay detection
├── graph/
│   ├── builder.py            # NetworkX DiGraph + SHA-256 file cache
│   ├── blast_radius.py       # BFS impact traversal
│   ├── community.py          # Leiden clustering (graspologic) + fallback
│   └── report.py             # GRAPH_REPORT.md generator
├── mcp/
│   ├── server.py             # MCP stdio server
│   └── tools.py              # 10 MCP tool implementations
├── install/
│   ├── claude.py             # .mcp.json + CLAUDE.md writer
│   ├── cursor.py             # .cursor/rules/infra-graph.mdc
│   └── codex.py              # AGENTS.md writer
├── viz/
│   └── html_report.py        # vis.js interactive HTML graph
└── cli.py                    # click CLI (8 commands)
```

**Tech stack:** NetworkX · Leiden (graspologic) · python-hcl2 · ruamel.yaml · vis.js · MCP Python SDK

**Privacy:** All parsing happens locally. No file contents leave your machine except during the optional `--mode deep` LLM pass, which uses your own API key. No telemetry. No cloud.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/parabvedang007/infra-graph
cd infra-graph
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

**Adding a new schema:** Create `parsers/yourformat_schema.py` implementing the `SchemaParser` protocol — `can_parse(path)` and `parse(path) → (nodes, edges)`. Add fixtures to `tests/fixtures/` and open a PR.

---

## License

MIT — see [LICENSE](LICENSE).

---

*Built by [Vedang Parab](mailto:parabvedang007@gmail.com)*
