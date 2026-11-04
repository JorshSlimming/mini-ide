"""Tests for mini_ide.git_state (local repositories only, no network)."""
import os
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
                    "head": None, "detached": False, "unborn": False,
                    "dirty": False}
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


def test_snapshot_can_skip_the_worktree_status_scan(tmp_path):
    root = _repo(tmp_path)
    (root / "a.txt").write_text("changed\n", encoding="utf-8")

    info = G.snapshot(str(root), check_dirty=False)

    assert info["branch"] == "main"
    assert info["dirty"] is None


def test_unborn_repository_reports_and_lists_its_branch(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")

    info = G.snapshot(str(root))

    assert info["is_repo"] is True
    assert info["unborn"] is True
    assert info["branch"] == "main"
    assert info["detached"] is False
    assert G.label(info) == "main"
    assert G.branches(str(root)) == ["main"]


def test_create_branch_in_unborn_repository(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")

    ok, message = G.create_branch(str(root), "feature/first")

    assert ok is True, message
    info = G.snapshot(str(root))
    assert info["unborn"] is True
    assert info["branch"] == "feature/first"
    assert G.branches(str(root)) == ["feature/first"]


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


def test_tracked_paths_includes_parent_directories(tmp_path):
    root = _repo(tmp_path)
    (root / "src" / "nested").mkdir(parents=True)
    (root / "src" / "nested" / "b.py").write_text("b\n", encoding="utf-8")
    _git(root, "add", "src/nested/b.py")

    paths = G.tracked_paths(str(root))

    assert os.path.normpath(str(root / "src" / "nested" / "b.py")) in paths
    assert os.path.normpath(str(root / "src" / "nested")) in paths
    assert os.path.normpath(str(root / "src")) in paths
    assert str(root) not in paths


def test_worktree_state_classifies_local_content(tmp_path):
    root = _repo(tmp_path)
    (root / ".gitignore").write_text(
        "ignored.env\nignored_dir/\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "tracked.py").write_text("x\n", encoding="utf-8")
    _git(root, "add", ".gitignore", "src/tracked.py")
    _git(root, "commit", "-q", "-m", "ignore rules")

    (root / "src" / "untracked.txt").write_text("u\n", encoding="utf-8")
    (root / "untracked.txt").write_text("u\n", encoding="utf-8")
    (root / "ignored.env").write_text("i\n", encoding="utf-8")
    (root / "ignored_dir").mkdir()
    (root / "ignored_dir" / "secret").write_text("i\n", encoding="utf-8")
    (root / "empty_dir").mkdir()

    state = G.worktree_state(str(root))

    assert state is not None
    assert state["root"] == str(root)
    assert os.path.normpath(str(root / "src")) in state["tracked"]
    assert os.path.normpath(str(root / "src" / "tracked.py")) in state["tracked"]
    assert os.path.normpath(str(root / "untracked.txt")) in state["untracked"]
    assert os.path.normpath(str(root / "src" / "untracked.txt")) in state["untracked"]
    assert os.path.normpath(str(root / "ignored.env")) in state["ignored"]
    assert os.path.normpath(str(root / "ignored_dir")) in state["ignored"]
    # src contains tracked and untracked files, so it is a mixed folder.
    assert os.path.normpath(str(root / "src")) in state["untracked_dirs"]
    assert str(root) not in state["tracked"]


def test_worktree_state_handles_names_with_spaces(tmp_path):
    root = _repo(tmp_path)
    (root / "folder with space").mkdir()
    (root / "folder with space" / "file name.txt").write_text(
        "x\n", encoding="utf-8")

    state = G.worktree_state(str(root))

    # Wholly untracked folders are collapsed to one root; the tree walks
    # ancestors, so descendants are still classified correctly.
    assert os.path.normpath(
        str(root / "folder with space")) in state["untracked"]
    assert os.path.normpath(str(root)) not in state["untracked"]


def test_worktree_state_limits_query_to_opened_subfolder(tmp_path):
    root = _repo(tmp_path)
    (root / "sub").mkdir()
    (root / "sub" / "tracked.py").write_text("x\n", encoding="utf-8")
    _git(root, "add", "sub/tracked.py")
    _git(root, "commit", "-q", "-m", "add sub")
    (root / "sub" / "untracked.py").write_text("u\n", encoding="utf-8")

    state = G.worktree_state(str(root / "sub"))

    assert os.path.normpath(str(root / "sub" / "tracked.py")) in state["tracked"]
    assert os.path.normpath(str(root / "sub" / "untracked.py")) in state["untracked"]
    # The tree for this panel only shows the opened subfolder; entries from
    # the rest of the repository are not needed and must not bloat state.
    assert os.path.normpath(str(root / "a.txt")) not in state["tracked"]


def test_worktree_state_rebases_paths_when_opened_through_symlink(tmp_path):
    root = _repo(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "tracked.py").write_text("x\n", encoding="utf-8")
    _git(root, "add", "src/tracked.py")
    _git(root, "commit", "-q", "-m", "add src")
    (root / "src" / "untracked.py").write_text("u\n", encoding="utf-8")
    link = tmp_path / "link"
    os.symlink(str(root), str(link))

    state = G.worktree_state(str(link))

    tracked = os.path.normpath(str(link / "src" / "tracked.py"))
    untracked = os.path.normpath(str(link / "src" / "untracked.py"))
    assert tracked in state["tracked"]
    assert untracked in state["untracked"]
    assert os.path.normpath(str(link / "src")) in state["untracked_dirs"]
    # Paths under the resolved repository path must not leak into the
    # tree's classification sets.
    assert os.path.normpath(str(root / "src" / "tracked.py")) not in state["tracked"]

    sub_link = tmp_path / "src-link"
    os.symlink(str(root / "src"), str(sub_link))
    sub_state = G.worktree_state(str(sub_link))
    assert os.path.normpath(str(sub_link / "tracked.py")) in sub_state["tracked"]
    assert os.path.normpath(str(sub_link / "untracked.py")) in sub_state["untracked"]


def test_worktree_state_non_repository_is_none(tmp_path):
    assert G.worktree_state(str(tmp_path)) is None


def test_worktree_state_git_missing_is_none(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(G.shutil, "which", lambda name: None)
    assert G.worktree_state(str(root)) is None


def test_switch_refuses_to_overwrite_ignored_file(tmp_path):
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("secret.env\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-q", "-m", "ignore secret")
    _git(root, "switch", "-q", "-c", "with-secret")
    (root / "secret.env").write_text("branch version\n", encoding="utf-8")
    _git(root, "add", "-f", "secret.env")
    _git(root, "commit", "-q", "-m", "track secret")
    _git(root, "switch", "-q", "main")
    (root / "secret.env").write_text("local version\n", encoding="utf-8")

    ok, message = G.switch_branch(str(root), "with-secret")

    assert ok is False
    assert "would be overwritten" in message.lower()
    assert (root / "secret.env").read_text(encoding="utf-8") == "local version\n"
    assert G.snapshot(str(root))["branch"] == "main"


def test_switch_refuses_to_overwrite_untracked_file(tmp_path):
    root = _repo(tmp_path)
    _git(root, "switch", "-q", "-c", "with-notes")
    (root / "notes.txt").write_text("branch version\n", encoding="utf-8")
    _git(root, "add", "notes.txt")
    _git(root, "commit", "-q", "-m", "add notes")
    _git(root, "switch", "-q", "main")
    (root / "notes.txt").write_text("local version\n", encoding="utf-8")

    ok, message = G.switch_branch(str(root), "with-notes")

    assert ok is False
    assert (root / "notes.txt").read_text(encoding="utf-8") == "local version\n"
    assert G.snapshot(str(root))["branch"] == "main"


def test_no_overwrite_ignore_option_detection():
    assert G._unsupported_no_overwrite_ignore(
        "error: unknown option `no-overwrite-ignore'")
    assert G._unsupported_no_overwrite_ignore(
        "fatal: unrecognized argument: --no-overwrite-ignore")
    assert not G._unsupported_no_overwrite_ignore(
        "error: Your local changes would be overwritten")


def test_switch_falls_back_to_checkout_when_switch_is_missing(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    calls = []

    def fake_switch(root_arg, args, name):
        calls.append(args)
        if args[0] == "switch":
            return False, "git: 'switch' is not a git command. See 'git --help'."
        return True, "Switched"

    monkeypatch.setattr(G, "_switch_result", fake_switch)
    ok, message = G.switch_branch(str(root), "main")

    assert ok is True, message
    assert calls[0][0] == "switch"
    assert calls[1][0] == "checkout"
    assert "--no-overwrite-ignore" in calls[1]


def test_switch_falls_back_when_safety_option_is_unknown(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    calls = []

    def fake_switch(root_arg, args, name):
        calls.append(args)
        if args[0] == "switch":
            return False, "error: unknown option `no-overwrite-ignore'"
        return True, "Switched"

    monkeypatch.setattr(G, "_switch_result", fake_switch)
    ok, message = G.switch_branch(str(root), "main")

    assert ok is True, message
    assert calls[1][0] == "checkout"
    assert "--no-overwrite-ignore" in calls[1]
