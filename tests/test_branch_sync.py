"""Tests for the pure branch-switch document reconciliation rules."""
from mini_ide import branch_sync as B


def test_file_digest_detects_content_and_missing_file(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("one\n", encoding="utf-8")
    first = B.file_digest(str(path))
    assert first
    path.write_text("two\n", encoding="utf-8")
    assert B.file_digest(str(path)) != first
    assert B.file_digest(str(tmp_path / "missing.txt")) is None


def test_disk_snapshot_tracks_size_and_missing_file(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("one\n", encoding="utf-8")
    snap = B.disk_snapshot(str(path))
    assert snap is not None
    assert snap[1] == 4
    assert B.disk_snapshot(str(tmp_path / "missing.txt")) is None


def test_unchanged_file_keeps_dirty_buffer():
    action = B.reconcile_action(
        dirty=True, conflict=False, deleted=False, disk_exists=True,
        before_digest="aaa", after_digest="aaa")
    assert action == B.UNCHANGED


def test_changed_file_conflicts_with_dirty_buffer():
    action = B.reconcile_action(
        dirty=True, conflict=False, deleted=False, disk_exists=True,
        before_digest="aaa", after_digest="bbb")
    assert action == B.CONFLICT


def test_changed_file_reloads_clean_buffer():
    action = B.reconcile_action(
        dirty=False, conflict=False, deleted=False, disk_exists=True,
        before_digest="aaa", after_digest="bbb")
    assert action == B.RELOAD


def test_missing_file_is_deleted():
    action = B.reconcile_action(
        dirty=True, conflict=False, deleted=False, disk_exists=False,
        before_digest="aaa", after_digest=None)
    assert action == B.DELETED


def test_reappeared_file_conflicts_with_dirty_buffer():
    action = B.reconcile_action(
        dirty=True, conflict=False, deleted=True, disk_exists=True,
        before_digest=None, after_digest="bbb")
    assert action == B.REAPPEARED_CONFLICT


def test_reappeared_file_reloads_clean_buffer():
    action = B.reconcile_action(
        dirty=False, conflict=False, deleted=True, disk_exists=True,
        before_digest=None, after_digest="bbb")
    assert action == B.REAPPEARED_RELOAD


def test_external_switch_uses_snapshot_fallback():
    unchanged = B.reconcile_action(
        dirty=True, conflict=False, deleted=False, disk_exists=True,
        before_digest=None, after_digest="bbb", snapshot_changed=False)
    conflict = B.reconcile_action(
        dirty=True, conflict=False, deleted=False, disk_exists=True,
        before_digest=None, after_digest="bbb", snapshot_changed=True)
    assert unchanged == B.UNCHANGED
    assert conflict == B.CONFLICT


def test_conflict_flag_counts_as_unsaved_state():
    action = B.reconcile_action(
        dirty=False, conflict=True, deleted=False, disk_exists=True,
        before_digest="aaa", after_digest="bbb")
    assert action == B.CONFLICT
