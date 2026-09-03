# iaclens

**Give your AI assistant a graph, not 70 raw files.**

iaclens is an infrastructure knowledge-graph MCP server. It parses your IaC files (Terraform, Kubernetes, ArgoCD, and more) into a dependency graph. It serves that graph to your AI assistant over MCP. The assistant reads a compact graph instead of every file. This saves tokens on every question.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=flat-square)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg?style=flat-square)](https://www.python.org/)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-green.svg?style=flat-square)](https://modelcontextprotocol.io/)
[![CI](https://github.com/ScrimReaper/iaclens/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrimReaper/iaclens/actions/workflows/ci.yml)

---

## Why use iaclens

Without a graph, your AI assistant reads your whole repo for every infrastructure question. A question like "what depends on this VPC?" can cost 30,000–70,000 tokens, because the assistant must scan every file.

iaclens builds the dependency graph once. After that, the assistant reads only the graph. A targeted query then costs a few hundred tokens instead of tens of thousands.

---

## Install

iaclens is not on PyPI. Install it from the git repository, or with Nix.

```bash
pip install git+https://github.com/ScrimReaper/iaclens
```

```bash
nix run github:ScrimReaper/iaclens -- --help
```

---

## Quick start

1. Go to your infrastructure repo.

   ```bash
   cd /path/to/your/infra-repo
   ```

2. Wire iaclens into your AI assistant. This writes the MCP config.

   ```bash
   iaclens install
   ```

   This detects your assistant and writes the right config. Supported platforms: `claude-code` (default), `cursor`, `codex`, `opencode`. Pick one directly with `--platform`:

   ```bash
   iaclens install --platform claude-code
   ```

3. Build the graph.

   ```bash
   iaclens build .
   ```

   This writes the graph to `iaclens-out/` and a summary to `GRAPH_REPORT.md`.

4. Restart your AI assistant, then ask it infrastructure questions:

   ```
   What is the blast radius if I delete the production VPC?
   Which Deployments use the app-config ConfigMap?
   Show me the full architecture overview.
   ```

   The assistant now reads the graph instead of your files.

To run the server manually, for an assistant iaclens does not auto-configure:

```bash
iaclens serve
```

This starts a local MCP stdio server. Point your assistant's MCP config at this command.

`iaclens serve` builds the graph once on startup, then watches the repo and rebuilds automatically whenever a parseable file (`.tf`/`.yml`/`.yaml`) changes. Each rebuild is a full rebuild, debounced so a burst of saves collapses into one rebuild instead of many. Files under `iaclens-out/`, `.git/`, any dot-directory, or excluded by `.infraignore` never trigger a rebuild.

Two environment variables control this:

- `IACLENS_NO_WATCH` — set to disable auto-watching (serve only builds once on startup).
- `IACLENS_WATCH_DEBOUNCE_MS` — debounce window in milliseconds (default `800`, clamped to `[100, 60000]`).

---

## What it parses

iaclens reads these formats and turns them into typed nodes and edges:

- **Terraform / OpenTofu** — resources, modules, variables, data sources, `depends_on`, interpolations
- **Kubernetes** — Deployments, Services, ConfigMaps, Secrets, and more, linked by label selectors
- **ArgoCD** — AppProjects, Applications, ApplicationSets, cluster targets
- **cert-manager** — Issuers and Certificates
- **External Secrets** — ExternalSecrets and SecretStores
- **Istio** — VirtualServices and DestinationRules
- **Flux CD** — HelmRelease, GitRepository, HelmRepository, Kustomization
- **Argo Rollouts** — canary/stable routing, analysis templates
- **KEDA** — ScaledObjects and their scale targets
- **Gateway API** — HTTPRoutes, Gateways
- **Ansible** — playbooks, roles, tasks, handlers, variables
- **GitHub Actions** — workflows, jobs, `uses:` and `needs:` references
- **Docker Compose** — services, volumes, networks
- **Helm** — charts, values, and templates (Go template syntax is stripped before parsing)
- **Kustomize** — base/overlay relationships

Any other YAML file still becomes a node, so nothing is silently dropped. Any unrecognized CRD becomes a typed node too, so custom operators (Velero, Crossplane, and so on) still show up in the graph.

### Ignoring files

Create `.infraignore` in your repo root. It uses the same syntax as `.gitignore`:

```
.terraform/
*.tfstate
*.tfstate.backup
dist/
node_modules/
```

---

## Commands

```bash
iaclens build .                 # parse the repo and build the graph
iaclens build . --update        # re-parse only changed files
iaclens build . --format json   # write graph.json instead of the default graph.toon

iaclens serve                   # start the MCP stdio server
iaclens install                 # wire iaclens into your AI assistant

iaclens status                  # show node/edge/community counts
iaclens query "<question>"      # search the graph from the terminal
iaclens blast-radius <node_id>  # list everything a change to <node_id> affects
iaclens path <from> <to>        # shortest dependency path between two nodes
iaclens visualize                # open an interactive HTML graph in your browser

iaclens federate <graph>...     # merge multiple repo graphs into one cross-repo graph
```

Run `iaclens <command> --help` for the full option list on any command.

### Graph federation

Large infrastructure estates often span several repos — one for Terraform, one for GitOps config, one for Helm charts. Build a graph in each repo, then merge them:

```bash
iaclens federate repo1/iaclens-out/graph.toon repo2/iaclens-out/graph.toon \
  --output ./federated-graph.toon
```

`iaclens federate` resolves cross-repo references by exact ID match, then fuzzy name match, then attribute match (for example, matching an ArgoCD cluster Secret to the Terraform cluster resource it points at). Serve the merged graph with:

```bash
iaclens serve --graph ./federated-graph.toon
```

Or register it alongside your normal graph as a second MCP server:

```bash
iaclens install --federated ./federated-graph.toon
```

---

## MCP tools

Once installed, your AI assistant calls these tools on its own:

| Tool | What it does |
|------|-------------|
| `get_minimal_context` | Compact orientation: god nodes, community count, totals. Start here. |
| `get_blast_radius` | Every resource affected by a change |
| `query_graph` | Graph traversal from any node |
| `get_resource_context` | Full detail on one resource |
| `get_architecture_overview` | Community map with coupling warnings |
| `detect_changes` | Risk-scored impact analysis for a git diff |
| `find_hub_nodes` | Most-connected resources |
| `get_knowledge_gaps` | Orphaned resources and unresolved references |
| `build_or_update_graph` | Trigger a rebuild from within the assistant |
| `search_resources` | Keyword search across the graph |

---

## Output format

`iaclens build` writes `graph.toon` by default. TOON (Token-Oriented Object Notation) encodes the graph in a compact tabular form, about 40% smaller in tokens than the same graph in JSON. Use `--format json` if you need the older `graph.json` format instead.

---

## About this fork

iaclens builds on [infra-graph](https://github.com/vparab7/infra-graph) (Apache-2.0) by Vedang Parab, and tracks it for upstream fixes. The Python module keeps its upstream name (`infra_graph`) so upstream changes merge cleanly.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Original work © Vedang Parab. Fork changes © the iaclens contributors.
