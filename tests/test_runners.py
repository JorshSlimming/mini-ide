"""Tests de mini_ide.runners (sin GTK, sin red, sin tocar units reales)."""
import json
import os

import mini_ide.runners as R


def _mk_runner(base, name, url, agent):
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".runner"), "w", encoding="utf-8-sig") as f:
        json.dump({"gitHubUrl": url, "agentName": agent}, f)
    return d


def test_unit_name():
    assert (R.unit_name("JorshSlimming", "pilltrack", "pilltrack-notebook")
            == "actions.runner.JorshSlimming-pilltrack."
               "pilltrack-notebook.service")


def test_discover_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "HOME", str(tmp_path))
    monkeypatch.setattr(R, "USER_SYSTEMD", str(tmp_path / "units"))
    _mk_runner(str(tmp_path), "actions-runner-foo",
               "https://github.com/Acme/foo", "foo-notebook")
    found = R.discover()
    assert found["foo"]["agent"] == "foo-notebook"
    assert found["foo"]["org"] == "Acme"
    assert found["foo"]["installed"] is False
    assert found["foo"]["unit"] == R.unit_name("Acme", "foo", "foo-notebook")


def test_resolve_by_basename(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "HOME", str(tmp_path))
    monkeypatch.setattr(R, "USER_SYSTEMD", str(tmp_path / "units"))
    _mk_runner(str(tmp_path), "actions-runner-bar",
               "https://github.com/Acme/bar", "bar-notebook")
    info = R.resolve(str(tmp_path / "projects" / "bar"))
    assert info["has_runner"] is True
    assert info["repo"] == "bar"


def test_resolve_no_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "HOME", str(tmp_path))
    info = R.resolve(str(tmp_path / "projects" / "nada"))
    assert info["has_runner"] is False


def test_local_state_unknown_unit():
    assert R.local_state(
        "definitivamente-no-existe-xyz.service") in (
            "inactive", "unknown", "failed")
