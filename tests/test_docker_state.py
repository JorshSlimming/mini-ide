"""Tests de mini_ide.docker_state (sin GTK, sin tocar contenedores)."""
import os

import mini_ide.docker_state as D


def test_resolve_found(tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}")
    info = D.resolve(str(tmp_path))
    assert info["has_docker"] is True
    assert info["compose"].endswith("compose.yaml")
    assert info["project"] == tmp_path.name


def test_resolve_alt_names(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}")
    assert D.resolve(str(tmp_path))["has_docker"] is True


def test_resolve_missing(tmp_path):
    info = D.resolve(str(tmp_path / "vacio"))
    assert info["has_docker"] is False


def test_state_of():
    assert D.state_of([]) == "off"
    assert D.state_of([{"state": "running"}]) == "on"
    assert D.state_of([{"state": "exited"}]) == "off"
    assert D.state_of([{"state": "running"}, {"state": "exited"}]) == "partial"
    assert D.summarize([{"state": "running"},
                        {"state": "exited"}]) == (1, 2)


def test_containers_no_root():
    assert D.containers({}) is None
    assert D.containers(None) is None


def test_containers_docker_down(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    info = D.resolve(str(tmp_path))
    monkeypatch.setattr(D, "_run", lambda *a, **k: None)
    assert D.containers(info) is None


def test_containers_bad_compose_is_empty(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    info = D.resolve(str(tmp_path))

    class R:
        returncode = 1
        stdout = ""
        stderr = "API_DOMAIN must be set"
    monkeypatch.setattr(D, "_run", lambda *a, **k: R())
    assert D.containers(info) == []


def test_containers_bad_dir_is_unknown(tmp_path):
    info = {"has_docker": True, "root": str(tmp_path / "no-existe-def"),
            "compose": "x", "project": "x"}
    assert D.containers(info) is None  # cwd inexistente: _run falla


def test_containers_parses_json_lines(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    info = D.resolve(str(tmp_path))

    class R:
        returncode = 0
        stdout = ('{"Name": "web-1", "State": "running", "Status": "Up"}\n'
                  'not-json\n'
                  '{"Name": "db-1", "State": "exited", "Status": "Exited"}\n')

    monkeypatch.setattr(D, "_run", lambda *a, **k: R())
    cts = D.containers(info)
    assert [(c["name"], c["state"]) for c in cts] == [
        ("web-1", "running"), ("db-1", "exited")]
    assert D.state_of(cts) == "partial"


def test_presentation_labels():
    info = {"has_docker": True, "project": "p", "root": "/tmp/p"}
    assert D.presentation(info)[0] == "wait"  # sin leer aún
    assert D.presentation(info, cts=[])[0] == "off"
    full = D.presentation(info, cts=[{"state": "running"}])
    assert full[:3] == ("on", "● DOCKER ON", "docker-on")
    assert "1/1 running" in full[3]
    part = D.presentation(info, cts=[{"state": "running"},
                                     {"state": "exited"}], compact=True)
    assert part[:3] == ("partial", "◐ PARTIAL", "docker-partial")
    assert "1/2 running" in part[3]
    missing = D.presentation({"has_docker": False, "root": "/tmp/p"})
    assert missing[:3] == ("none", "— NO DOCKER", "docker-none")
    assert "compose.yaml" in missing[3]


def test_find_compose_prefers_canonical(tmp_path):
    for name in ("docker-compose.yml", "compose.yaml"):
        (tmp_path / name).write_text("services: {}")
    assert os.path.basename(D.find_compose(str(tmp_path))) == "compose.yaml"
