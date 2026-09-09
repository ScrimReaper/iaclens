# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.0] — 2026-09-09

### Added
- `iaclens install --root <repo>` (repeatable) writes a multi-root
  `serve --path ...` MCP entry, so several repos are served as one live
  federated graph without editing `.mcp.json` by hand.

### Changed
- `build --update` (and the MCP tool's `update_only`) now means "rebuild only
  if a file was added, changed, or deleted". When nothing changed, the
  persisted graph is returned with no parsing. When something changed, a full
  rebuild runs. The old mode re-parsed only changed files and merged the old
  graph back in, which kept nodes of deleted files and missed cross-file edges
  (for example a new Service selecting an unchanged Deployment).
- All YAML parsing goes through one loader module (`parsers/_yaml.py`) that
  uses ruamel's `safe` loader with a line-capturing constructor instead of the
  round-trip loader. With `ruamel.yaml.clib` present (nixpkgs ships it) full
  builds are 3.5–4x faster (an Ansible repo with 900 files: 3.2s → 0.9s; a
  GitOps repo heavy in Helm templates: 6.7s → 1.6s); in pure Python about
  15–20%. Files the fast loader rejects but the round-trip loader accepts
  (unknown tags such as `!vault`, a stricter C scanner) fall back to the
  round-trip loader, so every file that parsed before still parses. Graph
  output is identical on eight real repos; the C scanner additionally accepts
  one file with a trailing tab that the pure loader rejects.

### Fixed
- Terraform/OpenTofu: a computed expression (`format(...)`, `local.n + 1`,
  `a ? b : c`, splats like `hcloud_server.node[*].ip`, for-comprehensions)
  used to become one `dynamic_ref` edge whose target was the raw expression
  text, i.e. a typeless `unknown` node named after the expression. The parser
  now links to every reference inside the expression (still `dynamic_ref`,
  provenance AMBIGUOUS) and never creates the expression node. Loop variables
  of for-comprehensions are skipped. A bare `module.<m>` reference is a
  `uses_module` edge to the module block instead of a mislabeled resource.

## [0.8.0] — 2026-09-09

### Added
- `iaclens serve --path A --path B ...` serves several repos as ONE federated
  graph. Each root is built with its own builder (and keeps its per-repo
  `iaclens-out/graph.toon`), the graphs are federated in-process, and the
  server serves the merged graph. Auto-watch covers every root: a change
  under one root rebuilds only that root and re-federates. `--out <file>`
  also writes the federated graph after each rebuild. This replaces the
  external "rebuild every repo, then `iaclens federate`" script that a
  static `serve --graph` needed to stay fresh. The MCP `build_or_update_graph`
  tool rebuilds a served root in place and re-federates.

### Fixed
- `iaclens serve` crashed on startup with `mcp` 2.x (`'Server' object has no
  attribute 'list_tools'`): the 2.x SDK removed the low-level decorator API
  in favour of constructor callbacks. The server now builds its handlers for
  whichever `mcp` major is installed (1.x decorators or 2.x callbacks). A new
  stdio test starts the real server and talks to it with the mcp client, so
  the suite catches this class of break from now on.
- The auto-watcher ignored file deletions, so a deleted file's nodes stayed in
  the served graph until some other file changed.
- A rebuild on the same builder (`serve` auto-watch) started from the
  previous run's parser state, so nodes and edges from deleted files
  survived every rebuild (k8s selector index, Ansible plays/roles). Parsers
  are now recreated per build.
- `build_or_update_graph` (MCP) reported `graph.json` as the written file; the
  default format is TOON, so it now reports `graph.toon`.
- Graph, JSON, and file-hash cache writes are atomic (temp file + rename), so a
  reader never sees a half-written graph while `serve` rebuilds it.
- `query`/`search_resources` count a repeated term once (`wazuh wazuh` no longer
  scores double).

### Changed
- The MCP server re-reads the graph file only when its (mtime, size) changed,
  instead of parsing it again on every tool call (about 27ms per call on a
  1400-node graph). A file that fails to load keeps the last good graph and is
  retried on the next call.
- The file walk prunes dot-directories (except `.github`) and `iaclens-out`
  instead of descending into them and filtering afterwards, so a large `.git`
  or `.terraform` tree is never visited.
- Federation resolves fuzzy unknowns through a base-name index instead of
  rescanning every node per unknown.
- The YAML dispatcher parses each file once and hands the parsed documents to
  the sub-parser it picks. Before, the Ansible sniff, the Ansible parser, and
  the Kubernetes parser each re-read and re-parsed the same file, so a plain
  manifest was parsed three times and an Ansible file twice. Builds are about
  1.8–2.2x faster on real repos (an Ansible repo with 900 YAML files: 4.9s →
  2.8s). Graph output is unchanged; Ansible vars/meta files are classified by
  path and no longer parsed at all.

## [0.7.1] — 2026-09-04

### Fixed
- Kubernetes parser no longer crashes on a Helm-templated `metadata.labels`. When
  a chart template renders `labels:` as a scalar (e.g.
  `{{- toYaml .Values.x | nindent 4 }}`), the stripped YAML leaves `labels` a
  string; `_get_labels` now treats any non-mapping value as no labels instead of
  raising `'str' object has no attribute 'items'` (seen on a redis-ha
  `PrometheusRule` template), which had dropped the whole file from the graph.

## [0.7.0] — 2026-09-04

### Added
- `iaclens completion <shell>` prints a shell completion hook for bash, zsh, or
  fish. It completes commands and options, and suggests graph node ids for the
  `blast-radius`, `query`, and `path` arguments once a graph is built. Node-id
  completion reads `iaclens-out/graph.toon` and stays silent (never errors) when
  no graph exists yet.
- The Nix package now installs bash, zsh, and fish completions into the standard
  completion directories (via `installShellFiles`), so completion works out of
  the box for any supported shell that sources those directories — no shell-rc
  changes needed on NixOS or home-manager.

### Fixed
- `query` now tokenizes multi-word input and ranks by matched terms, instead of
  matching the whole phrase as one literal substring (which returned nothing).
  CLI help and the argument name now say keyword search. CLI and MCP share one
  search helper.
- Terraform parser drops unresolvable interpolation targets (`templatefile(...)`,
  `for`-comprehensions, `path.*`/`terraform.*`/`self.*`) instead of emitting bogus
  references that became typeless `unknown` stub nodes.

## [0.6.0] — 2026-09-03

### Added
- `iaclens serve` now auto-watches the repository and keeps the graph fresh for the AI assistant. A burst of file saves is debounced (default 800ms, tunable with `IACLENS_WATCH_DEBOUNCE_MS`, clamped to 100ms–60s) into ONE full rebuild, so cross-file relationships stay correct. Disable with `IACLENS_NO_WATCH`; passing an explicit `--graph` serves a static graph and skips watching.

### Changed
- Removed the standalone `build --watch`. The MCP server (`serve`) owns watching now.

### Fixed
- The Docker Compose parser no longer warns on Jinja-templated compose files (e.g. an Ansible role's `templates/docker-compose.yml`); those are templates, not compose files, and are skipped quietly.

## [0.5.0] — 2026-09-03

Parser improvements. The graph now models real relationships instead of colliding on names.

### Added
- Path-qualified node IDs across parsers, so same-named resources in different directories no longer collide.
- Ansible: full parser rewrite. Roles link to their tasks, handlers, and vars. `notify` links to handlers. `include_tasks`/`import_tasks`/`include_role` resolve by path. `meta` dependencies link roles. `block`/`rescue`/`always` are followed. Playbooks no longer collapse every `roles/*/tasks/main.yml` onto one node.
- Terraform/OpenTofu: directory-qualified IDs (variables no longer collide across modules). Module `source` resolves to the child module directory. `module.<x>.<output>` resolves to the child output. `for_each`/`count` are recorded. Line numbers appear when the HCL parser exposes them.
- Kustomize: `resources:`/`bases:` entries link to the real workload nodes. Overlay IDs are directory-qualified.

### Changed
- README rewritten in plain language. SECURITY.md reporting contact updated.

## [0.4.0] — 2026-09-03

Forked from infra-graph. Added a reusable Nix flake; renamed the command and package to
`iaclens` (module `infra_graph` unchanged); made `--version` robust; removed the
non-functional `--mode deep` option and the PyPI publish workflow.

## [0.3.1] - 2026-04-27

### Changed

- **Docs:** Replaced all example node IDs in documentation and tests with generic names; fuzzy-match prefix examples now use common patterns (`org-`, `team-`, `prod-`, `staging-`) with a comment instructing users to extend the list for their own org.

## [0.3.0] - 2026-04-27

### Added

- **TOON output format (default):** `graph.toon` replaces `graph.json` as the default build output. TOON (Token-Oriented Object Notation) uses tabular encoding for uniform arrays, reducing graph size by ~40% compared to JSON. Use `infra-graph build . --format json` to opt in to the legacy JSON format. `load_graph` falls back to `.json` automatically if `.toon` is not found, preserving backward compatibility.
- **Graph federation (`infra-graph federate`):** Merges graphs from multiple repositories into a single cross-repo `federated-graph.toon`. Three resolution strategies are applied in order:
  - *Exact ID match* — an unknown node in repo A is resolved by a real node in repo B sharing the same node ID.
  - *Fuzzy/suffix match* — strips known org prefixes and matches on base name + type (e.g. `helm_chart/myapp` resolved to `helm_chart/org-myapp`); resolved edges are tagged `provenance=FEDERATED_FUZZY, confidence=0.7`.
  - *Attribute/value match* — ArgoCD cluster Secrets (`server_url`) are matched to Terraform `azurerm_kubernetes_cluster` resources and linked via `provisioned_by` edges (`provenance=FEDERATED_INFERRED, confidence=0.6`).
  - Federation output includes `meta` fields: `unknowns_resolved` and `provisioned_by_edges`.
- **ArgoCD cluster Secret `server_url` extraction:** When a Kubernetes Secret carries the label `argocd.argoproj.io/secret-type: cluster`, the parser now extracts `server_url` (resolved from `stringData.server` → `spec.server` → base64-decoded `data.server`) and `argocd_cluster_name` as node attributes. These attributes drive the federation attribute-match strategy.
- **MCP server `--graph` flag:** `infra-graph serve --graph /path/to/any-graph.toon` loads any graph file (local single-repo or federated) directly. The server resolves `.toon` or `.json` format from the file extension.
- **Dual-graph MCP install:** `infra-graph install --federated /path/to/federated-graph.toon` writes a second MCP server entry (`infra-graph-federated`) alongside the standard `infra-graph` entry. Claude Code discovers both servers and can query either scope.
- **Terraform output `expression` attribute:** `output` nodes now store the raw HCL `value` expression string as an `expression` attribute, allowing federation to trace cluster FQDN references across repositories.

## [0.2.0] - 2026-04-25

### Added

- **Universal K8s CRD support:** Removed the 29-kind allowlist gate in `k8s_schema.py`. Any YAML document with `apiVersion + kind + metadata` now produces a node — unknown CRDs (Velero, Crossplane, custom operators, etc.) are no longer silently dropped.
- **Istio:** `VirtualService` → `Service` (`routes_to`), `DestinationRule` → `Service` (`configures`) edge extraction.
- **Flux CD:** `HelmRelease` → `HelmRepository`/`GitRepository` (`from_repo`), `HelmRelease` → helm chart (`uses_chart`), `Kustomization` → `GitRepository` (`from_repo`), `Alert` → `Provider` (`uses_provider`) edge extraction.
- **Argo Rollouts:** `Rollout` → `Service` (`routes_to` for canary/stable services), `Rollout` → `AnalysisTemplate` (`uses_analysis`) edge extraction.
- **KEDA:** `ScaledObject` → `Deployment`/`StatefulSet` (`scales`) edge extraction, mirroring the existing HPA pattern.
- **Gateway API:** `HTTPRoute` → `Gateway` (`attached_to`), `HTTPRoute` → `Service` (`routes_to`) edge extraction.
- **Ansible parser** (`ansible_schema.py`): Detects and parses playbooks (play nodes, `uses_role` edges, `includes_tasks` edges) and task files.
- **Generic YAML fallback:** Any `.yml`/`.yaml` file that doesn't match any known schema now produces a `config/<stem>` node instead of being silently skipped.
- **27 new tests** in `tests/test_extensions.py` covering all new parsers and the unknown-CRD fallback.

## [0.1.2] - 2026-04-22

### Changed

- **License:** Switched from MIT to Apache 2.0.
- **Security:** Added CodeQL scanning workflow and Dependabot auto-update config.
- **Docs:** Clarified PyPI package name (`infra-graph7`) vs CLI command (`infra-graph`); fixed all repo URLs to `vparab7/infra-graph`.

## [0.1.1] - 2026-04-22

### Fixed

- **Parse-order bug for `selects_clusters` edges:** ApplicationSet cluster generator selectors are now resolved in a post-parse sweep (`resolve_cluster_selectors()`), the same way K8s Service label selectors work. Previously, zero `selects_clusters` edges were created if the ApplicationSet file was parsed before the cluster Secret file. Now 12 edges are correctly created on the benchmark repo.
- **ArgoCD multi-source Applications:** Both `Application` and `ApplicationSet` now extract `spec.sources` (list, ArgoCD 2.6+) in addition to `spec.source`. Helm chart sources create `uses_chart` edges.
- **Helm `__helm__` placeholder leaking into node IDs:** All field extractions in ArgoCD edge methods now route through `_safe_str()`, preventing phantom nodes named `AppProject/argocd/__helm__`.
- **Non-deterministic parse order:** Files are now sorted before parsing, making builds reproducible across runs.
- **Line numbers:** Nodes now include a 1-indexed `line` attribute extracted from ruamel.yaml's `.lc` metadata, enabling `get_resource_context` to report exact source locations.
- **`spec.destination.server` context:** Applications that use a server URL instead of a cluster name now store `dest_server` as a node attribute for AI context, without creating phantom edges.

### Added

- 8 new tests covering ArgoCD schemas (AppProject, Application, ApplicationSet, ExternalSecret, Certificate), Helm template stripping, `selects_clusters` post-parse resolution, and line number extraction.

## [0.1.0] - 2026-04-22

### Added

- Terraform / HCL parser: resources, modules, variables, outputs, locals, data sources, providers with 7 edge types (`references`, `depends_on`, `uses_var`, `uses_data`, `passes_input`, `uses_local`, `dynamic_ref`).
- Kubernetes manifest parser: 11 node types (Deployment, Service, ConfigMap, Secret, Ingress, Namespace, StatefulSet, DaemonSet, HPA, PVC, ServiceAccount) with cross-file label-selector sweep for `selects`/`routes_to` edges.
- GitHub Actions parser: jobs, steps, `needs:` dependencies, `uses:` action references, secret usage.
- Docker Compose parser: services, volumes, networks, `depends_on`, `shares_volume`, `shares_network`.
- Helm/Kustomize parser: chart metadata, `values*.yaml` overrides, `kustomization.yaml` bases/overlays/patches.
- SHA-256 file cache for incremental rebuilds (`--update`).
- `.infraignore` support (`.gitignore` syntax via `pathspec`).
- `--watch` mode for auto-rebuild on file saves.
- Community detection with Leiden algorithm (graspologic) and greedy modularity fallback.
- `GRAPH_REPORT.md` with god nodes, community map, surprising cross-community edges, and token benchmark.
- Interactive vis.js HTML visualization with type filter, community coloring, and click-to-inspect panel.
- 10 MCP tools: `get_minimal_context`, `get_blast_radius`, `query_graph`, `get_resource_context`, `get_architecture_overview`, `detect_changes`, `find_hub_nodes`, `get_knowledge_gaps`, `build_or_update_graph`, `search_resources`.
- `infra-graph install` for Claude Code, Cursor, Codex, and OpenCode.
- `/infra-graph` Claude Code skill.

[Unreleased]: https://github.com/ScrimReaper/iaclens/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/ScrimReaper/iaclens/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/ScrimReaper/iaclens/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/ScrimReaper/iaclens/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/ScrimReaper/iaclens/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/ScrimReaper/iaclens/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/ScrimReaper/iaclens/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/ScrimReaper/iaclens/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/vparab7/infra-graph/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/vparab7/infra-graph/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/vparab7/infra-graph/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/vparab7/infra-graph/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/vparab7/infra-graph/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/vparab7/infra-graph/releases/tag/v0.1.0
