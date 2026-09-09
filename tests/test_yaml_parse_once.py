"""The YAML dispatcher parses each file once and hands the parsed documents
to the sub-parser it picks, instead of every stage re-reading and re-parsing
the same file (the Ansible sniff, the Ansible parser, and the k8s parser each
used to load the file again)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from infra_graph.parsers import _yaml as yamlio
from infra_graph.parsers import ansible_schema
from infra_graph.parsers.yaml_parser import YAMLParser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def load_counter(monkeypatch):
    """Count every ruamel load across the dispatcher and its sub-parsers."""
    counts = {"n": 0}

    def _wrap(obj, name):
        real = getattr(obj, name)

        def counted(*a, **kw):
            counts["n"] += 1
            return real(*a, **kw)

        monkeypatch.setattr(obj, name, counted)

    _wrap(yamlio, "load")
    _wrap(yamlio, "load_all")
    return counts


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_plain_k8s_manifest_is_parsed_once(tmp_path, load_counter):
    f = _write(
        tmp_path,
        "deploy.yaml",
        """
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: web
          namespace: default
        spec: {}
        """,
    )
    result = YAMLParser(tmp_path).parse_file(f)
    assert [n["kind"] for n in result["nodes"]] == ["Deployment"]
    assert result["nodes"][0]["line"] == 2
    assert load_counter["n"] == 1


def test_ansible_task_file_with_jinja_is_parsed_once_and_keeps_names(tmp_path, load_counter):
    f = _write(
        tmp_path,
        "roles/web/tasks/main.yml",
        """
        - name: "Install {{ pkg }}"
          ansible.builtin.package:
            name: "{{ pkg }}"
        - include_tasks: "setup-{{ os }}.yml"
        """,
    )
    parser = YAMLParser(tmp_path)
    result = parser.parse_file(f)
    assert {n["type"] for n in result["nodes"]} >= {"task_file", "role"}
    # Jinja braces must not be mistaken for Helm directives and stripped.
    targets = [e["to"] for e in parser.finalize() if e["type"] == "includes_tasks"]
    assert targets == ["task_file/roles/web/tasks/setup-{{ os }}.yml"]
    assert load_counter["n"] == 1


def test_ansible_playbook_is_parsed_once(tmp_path, load_counter):
    f = _write(
        tmp_path,
        "site.yml",
        """
        - hosts: web
          roles:
            - web
        """,
    )
    result = YAMLParser(tmp_path).parse_file(f)
    assert any(n["type"] == "play" for n in result["nodes"])
    assert load_counter["n"] == 1


def test_generic_yaml_is_parsed_once(tmp_path, load_counter):
    f = _write(tmp_path, "conf.yml", "a: 1\nb: 2\n")
    result = YAMLParser(tmp_path).parse_file(f)
    assert result["nodes"][0]["type"] == "config"
    assert load_counter["n"] == 1


def test_vars_file_is_classified_by_path_without_parsing(tmp_path, load_counter):
    f = _write(tmp_path, "group_vars/web.yml", "pkg: nginx\n")
    result = YAMLParser(tmp_path).parse_file(f)
    assert result["nodes"][0]["id"] == "vars/group/web"
    assert load_counter["n"] == 0


def test_helm_template_still_yields_k8s_nodes(tmp_path):
    """A Go-templated manifest is stripped and parsed again. Behaviour is
    unchanged, only the plain-YAML path got cheaper."""
    f = _write(
        tmp_path,
        "templates/deploy.yaml",
        """
        {{- if .Values.enabled }}
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: {{ include "chart.fullname" . }}
          labels:
            {{- include "chart.labels" . | nindent 4 }}
        spec:
          replicas: {{ .Values.replicas }}
        {{- end }}
        """,
    )
    result = YAMLParser(tmp_path).parse_file(f)
    assert [n["kind"] for n in result["nodes"]] == ["Deployment"]


def test_multi_doc_manifest_is_not_sniffed_as_ansible(tmp_path, load_counter):
    f = _write(
        tmp_path,
        "bundle.yaml",
        """
        apiVersion: v1
        kind: Namespace
        metadata:
          name: a
        ---
        apiVersion: v1
        kind: Namespace
        metadata:
          name: b
        """,
    )
    result = YAMLParser(tmp_path).parse_file(f)
    assert sorted(n["name"] for n in result["nodes"]) == ["a", "b"]
    assert load_counter["n"] == 1


def test_ansible_parser_accepts_preparsed_doc(tmp_path, load_counter):
    """Direct callers may still pass only a path; the dispatcher passes the
    documents it already has."""
    f = _write(tmp_path, "roles/x/tasks/main.yml", "- name: t\n  debug:\n")
    p = ansible_schema.AnsibleParser(tmp_path)
    doc = [{"name": "t", "debug": None}]
    assert p.is_ansible_file(f, doc=doc) is True
    result = p.parse_file(f, doc=doc)
    assert any(n["type"] == "task_file" for n in result["nodes"])
    assert load_counter["n"] == 0


def test_helm_template_that_parses_raw_is_still_stripped(tmp_path):
    """`namespace: {{ .Release.Namespace }}` is valid YAML (a flow mapping),
    so the raw parse succeeds — with garbage keys. Templated non-Ansible
    files must always go through the strip step, never the raw documents."""
    f = _write(
        tmp_path,
        "templates/sa.yaml",
        """
        apiVersion: v1
        kind: ServiceAccount
        metadata:
          name: {{ include "chart.name" . }}
          namespace: {{ .Release.Namespace }}
        """,
    )
    result = YAMLParser(tmp_path).parse_file(f)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["kind"] == "ServiceAccount"
    assert node["name"] == "unknown"
    assert "ordereddict" not in node["id"]
