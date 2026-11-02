"""Tests for mini_ide.git_state (local repositories only, no network)."""
import shutil
import subprocess

import pytest

from mini_ide import git_state as G

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed")


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root)] + list(args), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _repo(tmp_path, branch="main"):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", branch)
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "PanelIDE Test")
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "initial")
    return root


def test_not_a_repository(tmp_path):
    info = G.snapshot(str(tmp_path))
    assert info == {"is_repo": False, "root": None, "branch": None,
                    "head": None, "detached": False, "dirty": False}
    assert G.branches(str(tmp_path)) == []
    assert G.label(info) == ""


def test_snapshot_reports_branch_and_dirty_state(tmp_path):
    root = _repo(tmp_path)
    info = G.snapshot(str(root))
    assert info["is_repo"] is True
    assert info["branch"] == "main"
    assert info["detached"] is False
    assert info["dirty"] is False
    assert G.label(info) == "main"

    (root / "a.txt").write_text("changed\n", encoding="utf-8")
    assert G.snapshot(str(root))["dirty"] is True


def test_snapshot_uses_repository_root_for_subfolders(tmp_path):
    root = _repo(tmp_path)
    sub = root / "src" / "nested"
    sub.mkdir(parents=True)
    info = G.snapshot(str(sub))
    assert info["is_repo"] is True
    assert info["root"] == str(root)
    assert info["branch"] == "main"


def test_detached_head_has_short_label(tmp_path):
    root = _repo(tmp_path)
    _git(root, "checkout", "--detach", "-q", "HEAD")
    info = G.snapshot(str(root))
    assert info["detached"] is True
    assert info["branch"] is None
    assert info["head"]
    assert G.label(info) == "detached@%s" % info["head"]


def test_branches_switch_and_create(tmp_path):
    root = _repo(tmp_path)
    _git(root, "branch", "feature/login")
    assert set(G.branches(str(root))) == {"main", "feature/login"}

    ok, message = G.switch_branch(str(root), "feature/login")
    assert ok is True, message
    assert G.snapshot(str(root))["branch"] == "feature/login"

    ok, message = G.create_branch(str(root), "feature/signup")
    assert ok is True, message
    info = G.snapshot(str(root))
    assert info["branch"] == "feature/signup"
    assert "feature/signup" in G.branches(str(root))


def test_switch_to_missing_branch_fails_without_changing_head(tmp_path):
    root = _repo(tmp_path)
    ok, message = G.switch_branch(str(root), "does-not-exist")
    assert ok is False
    assert message
    assert G.snapshot(str(root))["branch"] == "main"


def test_invalid_branch_name_is_rejected(tmp_path):
    root = _repo(tmp_path)
    for name in ("", "bad name", "-option", "a..b", "x~1"):
        ok, message = G.create_branch(str(root), name)
        assert ok is False
        assert message
    assert G.snapshot(str(root))["branch"] == "main"


def test_git_missing_is_handled(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(G.shutil, "which", lambda name: None)
    assert G.repo_root(str(root)) is None
    assert G.snapshot(str(root))["is_repo"] is False
    ok, message = G.switch_branch(str(root), "main")
    assert ok is False
    assert "Git is not available" in message
