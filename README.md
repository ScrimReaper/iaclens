# iaclens

**Stop asking your AI to read 70 files. Give it a graph.**

iaclens is a knowledge graph engine for infrastructure files. It parses your Terraform, Kubernetes, ArgoCD, GitHub Actions, Docker Compose, Helm, and Kustomize files, builds a structural dependency graph, and exposes it as an MCP server — so your AI assistant reads compact graph context instead of raw files on every question.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=flat-square)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg?style=flat-square)](https://www.python.org/)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-green.svg?style=flat-square)](https://modelcontextprotocol.io/)
[![CI](https://github.com/ScrimReaper/iaclens/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrimReaper/iaclens/actions/workflows/ci.yml)

---

## Why iaclens?

Every time you ask your AI assistant an infrastructure question, it reads your entire repo from scratch.

- "What does this EC2 instance depend on?" → AI reads all 80 `.tf` files
- "Which ConfigMap does this Deployment use?" → AI reads every manifest
- "What breaks if I change this ArgoCD AppProject?" → AI scans everything again

The cross-file relationships that matter — a Security Group referenced by 12 resources, a ConfigMap mounted by 5 Deployments, an ArgoCD ApplicationSet deploying 9 services to 3 clusters — are invisible without a graph.

**iaclens pre-indexes those relationships once. Every subsequent question reads the compact graph.**

| Approach | Tokens per query |
|----------|-----------------|
| AI reads all files (naive) | **~29,600–71,000** |
| `get_minimal_context` | **~300** |
| `get_blast_radius` (targeted) | **~500–800** |
| Full graph (worst case) | **~1,100** |

**Up to 65× token reduction on targeted queries.**

---

## Quick Start

> **Prerequisites:** Python 3.10+ · pip · An AI assistant with MCP support (Claude Code, Cursor, Codex, or OpenCode)

**Step 1 — Install**

```bash
pip install git+https://github.com/ScrimReaper/iaclens
```

Or with Nix:

```bash
nix run github:ScrimReaper/iaclens -- --help
```

> iaclens is not published to PyPI. Install it from the git repository, or via Nix.

**Step 2 — Go to your infrastructure repo**

```bash
cd /path/to/your/infra-repo
```

**Step 3 — Wire it into your AI assistant**

```bash
iaclens install
```

This auto-detects your AI assistant (Claude Code, Cursor, Codex, OpenCode) and writes the MCP config. Done — restart your AI assistant and it will use iaclens automatically.

**Step 4 — Build the graph**

```bash
iaclens build .
```

You'll see a `GRAPH_REPORT.md` appear in the current directory with a summary of your infrastructure: god nodes, communities, surprising connections, and token savings.

**Step 5 — Ask questions**

Open your AI assistant and ask:

```
What is the blast radius if I delete the production VPC?
Which Deployments use the app-config ConfigMap?
Show me the full architecture overview.
What secrets does the external-secrets operator manage?
Which services depend on this database?
```

The AI now reads compact graph context (~500 tokens) instead of all your files (~30,000 tokens).

---

## Installation Details

### Claude Code

```bash
iaclens install --platform claude-code
```

This writes:
- `.mcp.json` — MCP server config (Claude Code picks this up automatically on next launch)
- `CLAUDE.md` — instructs Claude to use iaclens tools before reading files

Then restart Claude Code. You'll see iaclens listed under available MCP servers.

You can also use the `/iaclens` slash command:

```
/iaclens .           # build + get orientation summary
/iaclens . --update  # incremental update after file changes
```

### Cursor

```bash
iaclens install --platform cursor
```

Writes `.cursor/rules/iaclens.mdc`. Restart Cursor to pick it up.

### Codex

```bash
iaclens install --platform codex
```

Writes `AGENTS.md` with tool usage instructions.

### OpenCode

```bash
iaclens install --platform opencode
```

### Manual / other assistants

```bash
iaclens serve   # starts the MCP stdio server
```

Point your assistant's MCP config at this command. The server speaks the standard MCP stdio protocol.

---

## Building the graph

```bash
iaclens build .                   # parse everything in current directory
iaclens build ./terraform         # only Terraform files
iaclens build ./k8s               # only Kubernetes manifests
iaclens build . --update          # re-parse only files that changed (fast)
iaclens build . --watch           # auto-rebuild on every file save
```

After each build, `GRAPH_REPORT.md` is written with:
- **God nodes** — highest-degree resources everything connects through
- **Communities** — automatically detected resource clusters (networking, compute, secrets, CI/CD)
- **Surprising edges** — cross-community connections worth reviewing
- **Token savings** — naive token cost vs. graph query cost for your repo

### Ignoring files

Create `.infraignore` in your repo root (same syntax as `.gitignore`):

```
.terraform/
*.tfstate
*.tfstate.backup
dist/
node_modules/
```

---

## What gets parsed

| Format | Extensions | What gets extracted |
|--------|-----------|---------------------|
| **Terraform / HCL** | `.tf` `.hcl` | Resources, modules, variables, outputs, locals, data sources, providers, `${}` interpolations, `depends_on` |
| **Kubernetes** | `.yaml` `.yml` with `apiVersion` | Deployments, Services, ConfigMaps, Secrets, Ingresses, StatefulSets, DaemonSets, HPAs, PVCs, ServiceAccounts + label→selector edges; ArgoCD cluster Secrets extract `server_url` and `argocd_cluster_name` for cross-repo federation |
| **ArgoCD** | `.yaml` with `argoproj.io` | AppProjects, Applications, ApplicationSets, cluster generators, `member_of` + `deploys_to` edges |
| **cert-manager** | `.yaml` with `cert-manager.io` | ClusterIssuers, Issuers, Certificates + `uses_issuer`, `creates_secret` edges |
| **External Secrets** | `.yaml` with `external-secrets.io` | ExternalSecrets, ClusterSecretStores + `uses_store` edges |
| **Istio** | `.yaml` with `networking.istio.io` | VirtualServices → Service (`routes_to`), DestinationRules → Service (`configures`) |
| **Flux CD** | `.yaml` with `*.fluxcd.io` | HelmRelease → HelmRepository/GitRepository (`from_repo`), Kustomization → GitRepository, Alert → Provider |
| **Argo Rollouts** | `.yaml` with `argoproj.io/v1alpha1 Rollout` | Rollout → Service (`routes_to` canary/stable), Rollout → AnalysisTemplate (`uses_analysis`) |
| **KEDA** | `.yaml` with `keda.sh` | ScaledObject → Deployment/StatefulSet (`scales`) |
| **Gateway API** | `.yaml` with `gateway.networking.k8s.io` | HTTPRoute → Gateway (`attached_to`), HTTPRoute → Service (`routes_to`) |
| **Unknown CRDs** | any `.yaml` with `apiVersion + kind + metadata` | Node created with the custom `kind`; no edges (works with Velero, Crossplane, custom operators, etc.) |
| **Ansible** | `.yaml` playbooks and task files | Play nodes, role nodes, task file nodes + `uses_role`, `includes_tasks` edges |
| **GitHub Actions** | `.yml` in `.github/workflows/` | Jobs, steps, `uses:` action refs, `needs:` deps, secret usage |
| **Docker Compose** | `docker-compose.yml` / `compose.yaml` | Services, volumes, networks, `depends_on` |
| **Helm** | `Chart.yaml` + `values*.yaml` | Chart metadata, value file override edges |
| **Helm templates** | `templates/*.yaml` | Go `{{}}` directives auto-stripped; static structure extracted cleanly |
| **Kustomize** | `kustomization.yaml` | Base/overlay `extends` and `patches` edges |
| **Generic YAML** | any other `.yml` / `.yaml` | Produces a `config/<filename>` node — nothing is silently dropped |

---

## MCP Tools

Once installed, your AI assistant calls these tools automatically. You can also ask it to call them explicitly.

| Tool | What it does |
|------|-------------|
| `get_minimal_context` | ~300-token orientation: god nodes, community count, totals. **Start here.** |
| `get_blast_radius` | Every resource affected by a change, with depth and edge type |
| `query_graph` | BFS/DFS traversal from any node in any direction |
| `get_resource_context` | Full detail on one resource: all edges, community, file, line number |
| `get_architecture_overview` | Community map with dominant types and coupling warnings |
| `detect_changes` | Risk-scored impact analysis for a git diff |
| `find_hub_nodes` | Top N highest-degree (most connected) resources |
| `get_knowledge_gaps` | Orphaned resources, ambiguous edges, unresolved references |
| `build_or_update_graph` | Trigger a rebuild or incremental update from within the AI |
| `search_resources` | Keyword search across node IDs, names, types, and labels |

### Node ID format

Use these IDs when calling tools directly:

| Resource type | Node ID format | Example |
|--------------|----------------|---------|
| Terraform resource | `resource.<type>.<name>` | `resource.aws_vpc.main` |
| Terraform variable | `variable.<name>` | `variable.region` |
| Terraform module | `module.<name>` | `module.vpc` |
| Kubernetes workload | `<Kind>/<namespace>/<name>` | `Deployment/default/api` |
| ArgoCD AppProject | `AppProject/<namespace>/<name>` | `AppProject/argocd/my-project` |
| ArgoCD Application | `Application/<namespace>/<name>` | `Application/argocd/frontend` |
| Compose service | `service/<project>/<name>` | `service/myapp/postgres` |
| GitHub Actions job | `job/<workflow>/<job_key>` | `job/ci/build` |
| Generic config file | `config/<filename>` | `config/my-config` |
| Ansible play | `play/<stem>/<hosts>` | `play/playbook/webservers` |

---

## Graph Federation

Large infrastructure estates are often split across multiple repositories — a `terraform-infra` repo that provisions clusters, a `gitops-config` repo with ArgoCD applications, and a `helm-charts` repo with chart definitions. Each repo builds its own graph. Federation merges them into a single cross-repo view so your AI can answer questions that span repository boundaries.

### How it works

Each repository builds its own `graph.toon` with `iaclens build`. The `iaclens federate` command then reads those graphs and resolves unknown references using three strategies (applied in order):

1. **Exact ID match** — an unresolved node in one repo is satisfied by a real node in another repo that shares the same node ID.
2. **Fuzzy/suffix match** — strips known org prefixes and matches on base name + node type. For example, `helm_chart/myapp` referenced in a GitOps repo is resolved to `helm_chart/org-myapp` in the charts repo; resolved edges are tagged `provenance=FEDERATED_FUZZY, confidence=0.7`.
3. **Attribute/value match** — ArgoCD cluster Secrets (which now expose a `server_url` attribute) are matched to Terraform `azurerm_kubernetes_cluster` resources. A `provisioned_by` edge is added between them (`provenance=FEDERATED_INFERRED, confidence=0.6`), linking GitOps config to the infrastructure that backs it.

The output is `federated-graph.toon` with federation metadata (`unknowns_resolved`, `provisioned_by_edges`) in the graph `meta` block.

### Usage

```bash
# Build individual graphs first
cd /path/to/terraform-infra  && iaclens build .
cd /path/to/gitops-config    && iaclens build .
cd /path/to/helm-charts      && iaclens build .

# Merge into a federated graph
iaclens federate \
  /path/to/terraform-infra/graph.toon \
  /path/to/gitops-config/graph.toon \
  /path/to/helm-charts/graph.toon \
  --output ./federated-graph.toon
```

### Serving the federated graph via MCP

Point the MCP server at any graph file with the `--graph` flag:

```bash
iaclens serve --graph ./federated-graph.toon
```

### Dual-graph install (single-repo + federated)

Register both the per-repo graph and the federated graph as separate MCP servers so Claude Code can query either scope:

```bash
iaclens install --federated ./federated-graph.toon
```

This writes two MCP server entries to `.mcp.json`:

- `iaclens` — the local single-repo graph (as before)
- `iaclens-federated` — the merged cross-repo graph

Claude Code discovers both servers on the next launch and selects the appropriate scope automatically.

---

## Output Format (TOON)

Starting in v0.3.0, `iaclens build` writes `graph.toon` by default instead of `graph.json`. TOON (Token-Oriented Object Notation) uses tabular encoding for uniform arrays (node lists, edge lists), producing files that are roughly **40% smaller in token count** than equivalent JSON — meaning even loading the full raw graph into an AI context window costs fewer tokens.

```bash
iaclens build .                   # writes graph.toon (default)
iaclens build . --format json     # opt in to legacy graph.json
```

`load_graph` automatically falls back to `.json` if `.toon` is not found, so existing workflows continue to work without changes.

---

## CLI Reference

```bash
# Build the graph
iaclens build .                     # full build (writes graph.toon by default)
iaclens build . --format json       # opt in to legacy graph.json output
iaclens build . --update            # incremental (only changed files)
iaclens build . --watch             # auto-rebuild on file saves

# Federate multiple repo graphs
iaclens federate repo1/graph.toon repo2/graph.toon repo3/graph.toon \
  --output ./federated-graph.toon

# Query from the terminal
iaclens query "what does aws_instance.web depend on?"
iaclens blast-radius resource.aws_vpc.main
iaclens path "Deployment/default/api" "ConfigMap/default/app-config"

# Inspect
iaclens status                      # node / edge / community counts
iaclens visualize                   # open interactive vis.js graph in browser

# Server
iaclens serve                       # start MCP stdio server (uses graph.toon)
iaclens serve --graph /path/to/federated-graph.toon   # load any graph file

# Install
iaclens install                     # auto-detect AI assistant
iaclens install --platform claude-code
iaclens install --platform cursor
iaclens install --platform codex
iaclens install --platform opencode
iaclens install --federated ./federated-graph.toon    # add dual-graph MCP entry
```

---

## Benchmarks

| Corpus | Files | Naive tokens/query | Graph tokens/query | Reduction |
|--------|-------|--------------------|-------------------|-----------|
| AWS three-tier Terraform | 38 `.tf` | ~31,000 | ~520 | **~60×** |
| Kubernetes GitOps repo | 120 manifests | ~48,000 | ~980 | **~49×** |
| Mixed monorepo (TF + k8s + Actions) | 160 | ~71,000 | ~1,100 | **~65×** |
| ArgoCD GitOps repo | 70 YAML | ~29,600 | ~650 | **~46×** |
| Small single-service Compose | 4 files | ~1,200 | ~950 | ~1.3× |

> **Small repo note:** For repos under ~20 files, graph overhead can exceed raw file size. iaclens pays off at scale — when questions span multiple files and change frequently.

---

## How it works

**Pass 1 — Structural parse (no LLM)**
Terraform files are parsed with `python-hcl2`. YAML files are parsed with `ruamel.yaml`. Helm templates have Go `{{}}` directives stripped before parsing. Every resource, module, variable, workload, ArgoCD app, cert, and workflow job becomes a typed node. Every interpolation, dependency, and selector reference becomes a typed edge.

**Pass 2 — Schema-aware inference (no LLM)**
Kubernetes label-selector matching runs as a cross-file sweep: a label inverted index is built, then Service selectors are matched against Deployment labels to create `routes_to` edges. ArgoCD cluster generator `matchLabels` are matched against cluster Secrets. Helm and Kustomize overlay relationships are detected as `extends`/`patches` edges.

**Output — TOON serialization**
After both passes, the graph is serialized to `graph.toon` using TOON (Token-Oriented Object Notation). Uniform arrays (node lists, edge lists) are encoded in a compact tabular form that is ~40% smaller in token count than equivalent JSON. Use `--format json` to opt in to the legacy format.

**Optional — Federation pass (`iaclens federate`)**
Graphs from multiple repositories can be merged into a single `federated-graph.toon` using three resolution strategies: exact node ID match, fuzzy prefix-strip + type match, and attribute/value match (ArgoCD cluster `server_url` → Terraform cluster resource). See [Graph Federation](#graph-federation) for details.

---

## Architecture

```
infra_graph/
├── parsers/
│   ├── tf_parser.py          # python-hcl2 + ${} interpolation extractor
│   ├── yaml_parser.py        # ruamel.yaml + Helm template pre-processor + generic fallback
│   ├── k8s_schema.py         # K8s + ArgoCD + Istio + Flux + KEDA + Gateway API + any CRD
│   ├── ansible_schema.py     # Ansible playbook + task file parser
│   ├── actions_schema.py     # GitHub Actions job/step/uses graph
│   ├── compose_schema.py     # Docker Compose service graph
│   └── helm_schema.py        # Helm Chart.yaml + Kustomize overlay detection
├── graph/
│   ├── builder.py            # NetworkX DiGraph + SHA-256 file cache
│   ├── blast_radius.py       # BFS impact traversal
│   ├── community.py          # community detection clustering + fallback
│   ├── report.py             # GRAPH_REPORT.md generator
│   ├── toon.py               # TOON serializer/deserializer (default output format)
│   └── federation.py         # multi-repo graph federation engine
├── mcp/
│   ├── server.py             # MCP stdio server
│   └── tools.py              # 10 MCP tool implementations
├── install/
│   ├── claude.py             # .mcp.json + CLAUDE.md writer
│   ├── cursor.py             # .cursor/rules/iaclens.mdc
│   └── codex.py              # AGENTS.md writer
├── viz/
│   └── html_report.py        # vis.js interactive HTML graph
└── cli.py                    # click CLI
```

**Privacy:** All parsing happens locally. No file contents leave your machine. No telemetry. No cloud.

---

## Contributing

```bash
git clone https://github.com/ScrimReaper/iaclens
cd iaclens
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on adding new parsers and schemas.

---

## About this fork

iaclens is an infrastructure knowledge-graph MCP server. It builds on
[infra-graph](https://github.com/vparab7/infra-graph) (Apache-2.0) by Vedang
Parab and tracks it for upstream fixes. The internal Python module keeps its
upstream name (`infra_graph`) so upstream changes merge cleanly.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Original work © Vedang Parab. Fork changes © the iaclens contributors.

---

*Originally built by [Vedang Parab](mailto:parabvedang007@gmail.com); fork maintained by [ScrimReaper](https://github.com/ScrimReaper).*
