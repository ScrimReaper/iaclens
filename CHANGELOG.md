# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/vparab7/infra-graph/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/vparab7/infra-graph/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/vparab7/infra-graph/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/vparab7/infra-graph/releases/tag/v0.1.0
