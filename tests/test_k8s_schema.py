"""Tests for the Kubernetes schema parser."""

from pathlib import Path

import pytest

from infra_graph.parsers.k8s_schema import KubernetesParser
from infra_graph.parsers.yaml_parser import YAMLParser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def k8s_result():
    parser = KubernetesParser()
    result = parser.parse_file(FIXTURES / "k8s_deployment.yaml")
    return result, parser


def test_parse_returns_nodes_and_edges(k8s_result):
    result, _ = k8s_result
    assert "nodes" in result
    assert "edges" in result
    assert len(result["nodes"]) > 0


def test_deployment_node_extracted(k8s_result):
    result, _ = k8s_result
    node_ids = {n["id"] for n in result["nodes"]}
    assert "Deployment/default/myapp" in node_ids


def test_service_node_extracted(k8s_result):
    result, _ = k8s_result
    node_ids = {n["id"] for n in result["nodes"]}
    assert "Service/default/myapp-svc" in node_ids


def test_configmap_node_extracted(k8s_result):
    result, _ = k8s_result
    node_ids = {n["id"] for n in result["nodes"]}
    assert "ConfigMap/default/app-config" in node_ids


def test_ingress_node_extracted(k8s_result):
    result, _ = k8s_result
    node_ids = {n["id"] for n in result["nodes"]}
    assert "Ingress/default/myapp-ingress" in node_ids


def test_hpa_node_extracted(k8s_result):
    result, _ = k8s_result
    node_ids = {n["id"] for n in result["nodes"]}
    assert "HPA/default/myapp-hpa" in node_ids


def test_configmap_mount_edge(k8s_result):
    """Deployment mounts ConfigMap via envFrom."""
    result, _ = k8s_result
    mount_edges = [e for e in result["edges"] if e["type"] == "mounts_config"]
    assert len(mount_edges) >= 1
    froms = {e["from"] for e in mount_edges}
    assert "Deployment/default/myapp" in froms


def test_secret_mount_edge(k8s_result):
    """Deployment references secret via secretKeyRef."""
    result, _ = k8s_result
    mount_edges = [e for e in result["edges"] if e["type"] == "mounts_secret"]
    assert len(mount_edges) >= 1
    froms = {e["from"] for e in mount_edges}
    assert "Deployment/default/myapp" in froms


def test_ingress_exposes_edge(k8s_result):
    """Ingress should have exposes edge to Service."""
    result, _ = k8s_result
    expose_edges = [e for e in result["edges"] if e["type"] == "exposes"]
    assert len(expose_edges) >= 1
    pairs = {(e["from"], e["to"]) for e in expose_edges}
    assert ("Ingress/default/myapp-ingress", "Service/default/myapp-svc") in pairs


def test_hpa_scales_edge(k8s_result):
    """HPA should have scales edge to Deployment."""
    result, _ = k8s_result
    scales_edges = [e for e in result["edges"] if e["type"] == "scales"]
    assert len(scales_edges) >= 1
    pairs = {(e["from"], e["to"]) for e in scales_edges}
    assert ("HPA/default/myapp-hpa", "Deployment/default/myapp") in pairs


def test_node_schema(k8s_result):
    """Every node must have required schema fields."""
    result, _ = k8s_result
    required_fields = {"id", "type", "kind", "name", "file", "line", "labels"}
    for node in result["nodes"]:
        missing = required_fields - set(node.keys())
        assert not missing, f"Node {node.get('id')} missing fields: {missing}"


def test_edge_provenance(k8s_result):
    """Kubernetes edges should have EXTRACTED or INFERRED provenance."""
    result, _ = k8s_result
    valid = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}
    for edge in result["edges"]:
        assert edge.get("provenance") in valid


def test_labels_captured(k8s_result):
    """ConfigMap and Deployment should have labels captured."""
    result, _ = k8s_result
    nodes_by_id = {n["id"]: n for n in result["nodes"]}
    cm = nodes_by_id.get("ConfigMap/default/app-config")
    assert cm is not None
    assert cm["labels"].get("app") == "myapp"


def test_selector_resolution(k8s_result):
    """Service with selector app=myapp should resolve to Deployment via routes_to."""
    _, parser = k8s_result
    # Store the Service's selector manually (simulate what yaml_parser.finalize does)
    parser.store_selector("Service/default/myapp-svc", {"app": "myapp"})
    extra_edges = parser.resolve_selectors()
    routes_edges = [e for e in extra_edges if e["type"] == "routes_to"]
    assert len(routes_edges) >= 1
    pairs = {(e["from"], e["to"]) for e in routes_edges}
    assert ("Service/default/myapp-svc", "Deployment/default/myapp") in pairs


def test_node_namespace_set(k8s_result):
    """All nodes should have namespace attribute."""
    result, _ = k8s_result
    for node in result["nodes"]:
        assert "namespace" in node
        assert node["namespace"] == "default"


def test_parse_nonexistent_file():
    """Parsing a nonexistent file should return empty result."""
    parser = KubernetesParser()
    result = parser.parse_file(Path("/nonexistent/k8s.yaml"))
    assert result["nodes"] == []
    assert result["edges"] == []


# ── ArgoCD + cert-manager + ESO tests ─────────────────────────────────────────

@pytest.fixture()
def argocd_result():
    parser = KubernetesParser()
    result = parser.parse_file(FIXTURES / "argocd_resources.yaml")
    return result, parser


def test_argocd_appproject_parsed(argocd_result):
    """AppProject node should be extracted from ArgoCD YAML."""
    result, _ = argocd_result
    node_ids = {n["id"] for n in result["nodes"]}
    assert "AppProject/argocd/myapp" in node_ids


def test_argocd_application_member_of_edge(argocd_result):
    """Application should have member_of edge to AppProject."""
    result, _ = argocd_result
    member_edges = [e for e in result["edges"] if e["type"] == "member_of"]
    pairs = {(e["from"], e["to"]) for e in member_edges}
    assert ("Application/argocd/myapp-app", "AppProject/argocd/myapp") in pairs


def test_argocd_applicationset_member_of_edge(argocd_result):
    """ApplicationSet should have member_of edge to AppProject."""
    result, _ = argocd_result
    member_edges = [e for e in result["edges"] if e["type"] == "member_of"]
    pairs = {(e["from"], e["to"]) for e in member_edges}
    assert ("ApplicationSet/argocd/myapp-appset", "AppProject/argocd/myapp") in pairs


def test_helm_template_stripping():
    """Helm template directives should be stripped before K8s parse."""
    parser = YAMLParser()
    result = parser.parse_file(FIXTURES / "helm_template.yaml")
    # AppProject should be extracted even though name was a Helm expression
    node_types = {n["type"] for n in result["nodes"]}
    assert "AppProject" in node_types
    # Name falls back to "unknown" because {{ .Values.projectName }} → __helm__ → None
    node_ids = {n["id"] for n in result["nodes"]}
    assert "AppProject/argocd/unknown" in node_ids


def test_externalsecret_uses_store_edge(argocd_result):
    """ExternalSecret should have uses_store edge to ClusterSecretStore."""
    result, _ = argocd_result
    store_edges = [e for e in result["edges"] if e["type"] == "uses_store"]
    assert len(store_edges) >= 1
    pairs = {(e["from"], e["to"]) for e in store_edges}
    assert ("ExternalSecret/default/my-secret", "ClusterSecretStore/default/my-store") in pairs


def test_certificate_edges(argocd_result):
    """Certificate should have uses_issuer and creates_secret edges."""
    result, _ = argocd_result
    issuer_edges = [e for e in result["edges"] if e["type"] == "uses_issuer"]
    secret_edges = [e for e in result["edges"] if e["type"] == "creates_secret"]
    assert len(issuer_edges) >= 1
    assert len(secret_edges) >= 1
    issuer_pairs = {(e["from"], e["to"]) for e in issuer_edges}
    secret_pairs = {(e["from"], e["to"]) for e in secret_edges}
    assert ("Certificate/default/my-cert", "ClusterIssuer/default/letsencrypt") in issuer_pairs
    assert ("Certificate/default/my-cert", "Secret/default/my-tls-secret") in secret_pairs


def test_selects_clusters_post_parse():
    """ApplicationSet cluster selector should match Secret labels even if appset parsed first."""
    parser = KubernetesParser()
    # Parse ApplicationSet BEFORE the cluster Secret (reverse order to verify post-parse fix)
    parser.parse_file(FIXTURES / "applicationset_with_cluster_gen.yaml")
    parser.parse_file(FIXTURES / "cluster_secret.yaml")
    extra_edges = parser.resolve_cluster_selectors()
    selects_edges = [e for e in extra_edges if e["type"] == "selects_clusters"]
    assert len(selects_edges) >= 1
    pairs = {(e["from"], e["to"]) for e in selects_edges}
    assert ("ApplicationSet/argocd/cluster-appset", "Secret/argocd/staging-cluster") in pairs


def test_line_numbers_extracted(argocd_result):
    """Nodes should have non-null line numbers when parsed from YAML."""
    result, _ = argocd_result
    for node in result["nodes"]:
        assert node["line"] is not None, f"Node {node['id']} has null line number"
        assert isinstance(node["line"], int)
        assert node["line"] >= 1
