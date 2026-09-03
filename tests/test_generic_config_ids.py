from infra_graph.parsers.yaml_parser import YAMLParser


def test_same_named_generic_yaml_do_not_collide(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "conf.yml").write_text("foo: 1\n")
    (tmp_path / "b" / "conf.yml").write_text("bar: 2\n")
    p = YAMLParser(tmp_path)
    id_a = p.parse_file(tmp_path / "a" / "conf.yml")["nodes"][0]["id"]
    id_b = p.parse_file(tmp_path / "b" / "conf.yml")["nodes"][0]["id"]
    assert id_a != id_b
    assert id_a == "config/a/conf.yml#conf"
