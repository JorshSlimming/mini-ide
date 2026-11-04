"""Regression tests for the GTK-side branch-operation guards.

These tests do not open a display: they call the real ProjectPanel methods
on a blank GObject instance with fake widgets/stores. GTK is still required
for the import, so the module skips cleanly on a non-GTK machine.
"""
import os
import threading

import pytest

pytest.importorskip("gi")
try:
    import panelide
except Exception as exc:  # pragma: no cover - depends on the host
    pytest.skip("PanelIDE GTK stack unavailable: %s" % exc,
                allow_module_level=True)


def _panel():
    # GObject requires its own __new__; __init__ (which needs a display and
    # spawns terminals) is deliberately not called.
    return panelide.ProjectPanel.__new__(panelide.ProjectPanel)


class _Store:
    def __init__(self):
        self.removed = []

    def iter_is_valid(self, it):
        return True

    def remove(self, it):
        self.removed.append(it)


class _Ctx:
    def __init__(self):
        self.calls = []

    def finish(self, *args):
        self.calls.append(args)


class _Data:
    def __init__(self, uris):
        self._uris = uris

    def get_uris(self):
        return self._uris


class _Label:
    def __init__(self):
        self.text = None

    def set_text(self, text):
        self.text = text


class _Button:
    def set_sensitive(self, value):
        self.sensitive = value

    def get_style_context(self):
        return self

    def add_class(self, name):
        pass


class _Tabs:
    def __init__(self, widget):
        self.widget = widget

    def get_current_page(self):
        return 0

    def get_nth_page(self, page):
        return self.widget


class _Term:
    def kill_sync(self, *args):
        pass


class _Doc:
    def __init__(self, path):
        self.path = path
        self.buffer = object()
        self.dirty = True
        self.deleted = False
        self.conflict = False
        self.unsafe = False
        self.unsafe_reason = ""
        self.saved_snap = None
        self.strict_utf8 = True
        self.resumed = 0

    def cancel_autosave(self):
        pass

    def resume_autosave(self):
        if self.dirty and not self.conflict and not self.deleted and not self.unsafe:
            self.resumed += 1
            return True
        return False

    def mark_conflict(self):
        self.conflict = True
        self.unsafe = False
        self.unsafe_reason = ""

    def mark_unsafe(self, reason):
        self.mark_conflict()
        self.unsafe = True
        self.unsafe_reason = reason

    def resolve_reload(self):
        self.dirty = False
        self.conflict = False
        self.unsafe = False
        self.unsafe_reason = ""

    def resolve_keep_local(self):
        self.conflict = False
        self.unsafe = False
        self.unsafe_reason = ""
        self.resumed += 1

    def recreate(self):
        self.deleted = False
        self.dirty = False
        self.conflict = False
        self.unsafe = False

    def save_as(self, new_path):
        self.path = new_path
        self.deleted = False
        self.dirty = False
        self.conflict = False
        self.unsafe = False


def test_drop_copy_is_refused_while_git_switches(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "dropped.txt"
    src.write_text("local\n", encoding="utf-8")
    uri = panelide.GLib.filename_to_uri(str(src), None)

    for handler in ("on_drop", "on_root_drop"):
        panel = _panel()
        panel.root = str(root)
        panel._branch_op = True
        panel._branch_busy_dialog = lambda: None
        panel._do_refresh = lambda: None
        panel._tree_drop_destination = lambda *a: str(root)
        ctx = _Ctx()

        getattr(panel, handler)(None, ctx, 0, 0, _Data([uri]), 80, 123)

        assert not (root / "dropped.txt").exists()
        assert ctx.calls == [(False, False, 123)]


def test_drop_copy_still_works_when_git_is_idle(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "dropped.txt"
    src.write_text("local\n", encoding="utf-8")
    uri = panelide.GLib.filename_to_uri(str(src), None)

    panel = _panel()
    panel.root = str(root)
    panel._branch_op = False
    panel._do_refresh = lambda: None
    panel._tree_drop_destination = lambda *a: str(root)
    ctx = _Ctx()

    panel.on_drop(None, ctx, 0, 0, _Data([uri]), 80, 123)

    assert (root / "dropped.txt").read_text(encoding="utf-8") == "local\n"
    assert ctx.calls == [(True, False, 123)]


def test_open_file_is_refused_while_git_switches(tmp_path):
    path = tmp_path / "notes"
    path.write_text("data\n", encoding="utf-8")
    opened = []

    panel = _panel()
    panel._branch_op = True
    panel._branch_busy_dialog = lambda: None
    panel.open_text = lambda p: opened.append(p)

    panel.open_file(str(path))
    assert opened == []

    panel._branch_op = False
    panel.open_file(str(path))
    assert opened == [str(path)]


def test_pending_new_file_is_cancelled_before_switch(tmp_path):
    it = object()
    store = _Store()
    panel = _panel()
    panel.store = store
    panel._pending = (it, "newfile", str(tmp_path))
    panel.branch_lbl = _Label()
    panel.branch_btn = _Button()
    panel._branch_op = False
    panel._pause_docs_for_branch = lambda: []

    original = threading.Thread
    started = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append(self.target)

    threading.Thread = FakeThread
    try:
        panel._switch_branch("feature")
    finally:
        threading.Thread = original

    assert panel._pending is None
    assert store.removed == [it]
    assert panel._branch_op is True
    assert len(started) == 1


def test_name_edit_cannot_create_while_git_switches(tmp_path):
    it = object()
    store = _Store()
    panel = _panel()
    panel.store = store
    panel._pending = (it, "newfile", str(tmp_path))
    panel._branch_op = True
    panel._branch_busy_dialog = lambda: None

    panel.on_name_edited(None, "0", "must-not-exist.txt")

    assert panel._pending is None
    assert store.removed == [it]
    assert not (tmp_path / "must-not-exist.txt").exists()


def test_stale_name_edit_cannot_rename_a_different_row(tmp_path):
    class _StoreWithRow:
        def get_iter(self, path_str):
            return object()

        def get_value(self, it, column):
            return {3: "file", 2: str(tmp_path / "other.txt")}[column]

    renamed = []
    panel = _panel()
    panel.store = _StoreWithRow()
    panel._pending = None
    panel._branch_op = False
    panel._edit_target = str(tmp_path / "original.txt")
    panel.rename_path = lambda old, new: renamed.append((old, new))

    panel.on_name_edited(None, "0", "renamed.txt")

    assert renamed == []


def test_stale_branch_info_is_ignored_and_pending_refresh_runs():
    applied = []
    refreshed = []
    panel = _panel()
    panel._branch_info_gen = 5
    panel._branch_info_busy = True
    panel._branch_info_pending = True
    panel._branch_info_reconcile = False
    panel._shutdown = False
    panel._branch_op = False
    panel._apply_branch_snapshot = lambda info, reconcile=True: applied.append(
        (info, reconcile))
    panel._branch_refresh = lambda **kw: refreshed.append(kw)

    panel._apply_branch_info(4, {"is_repo": False}, [], True)
    assert applied == []
    assert panel._branch_info_busy is True

    panel._apply_branch_info(5, {"is_repo": True, "branch": "main"}, ["main"],
                             True)
    assert applied == [({"is_repo": True, "branch": "main"}, True)]
    assert refreshed == [{"reconcile": False}]


def test_unchanged_branch_uses_the_worktree_ttl_cache():
    calls = []
    panel = _panel()
    panel.root = "/repo"
    panel.git_info = {"is_repo": True, "branch": "main", "head": None,
                      "unborn": False}
    panel._worktree_state_root = "/repo"
    panel._tree_git_ready = True
    panel.docs = {}
    panel._worktree_state_for = lambda root, force=False: calls.append(
        (root, force))
    panel._do_refresh = lambda: None
    panel._branch_paint = lambda: None

    panel._apply_branch_snapshot(
        {"is_repo": True, "branch": "main", "head": None, "unborn": False},
        reconcile=True)

    assert calls == [("/repo", False)]


def test_refresh_after_branch_forces_a_fresh_classification(tmp_path):
    calls = []
    panel = _panel()
    panel.root = str(tmp_path)
    panel._refresh_id = None
    panel._tree_git_ready = False
    panel._state_cache = {}
    panel.git_info = {"is_repo": True}
    panel._worktree_state_for = lambda root, force=False: calls.append(
        ("state", root, force))
    panel._do_refresh = lambda: calls.append(("tree",))
    panel._branch_paint = lambda: None
    panel._branch_refresh = lambda **kw: calls.append(("branch", kw))

    panel._refresh_after_branch()

    assert ("state", str(tmp_path), True) in calls
    assert ("tree",) in calls
    assert ("branch", {"reconcile": False}) in calls


def test_external_branch_change_reconciles_open_documents(tmp_path):
    reconciled = []
    panel = _panel()
    panel.root = str(tmp_path)
    panel.git_info = {"is_repo": True, "branch": "main", "head": None,
                      "unborn": False}
    panel._worktree_state_root = str(tmp_path)
    panel._tree_git_ready = True
    panel.docs = {object(): object()}
    panel._worktree_state_for = lambda root, force=False: None
    panel._do_refresh = lambda: None
    panel._branch_paint = lambda: None
    panel._reconcile_open_docs_external = lambda: reconciled.append(True)

    panel._apply_branch_snapshot(
        {"is_repo": True, "branch": "feature", "head": None,
         "unborn": False}, reconcile=True)
    panel._apply_branch_snapshot(
        {"is_repo": True, "branch": "feature", "head": None,
         "unborn": False}, reconcile=True)

    assert reconciled == [True]


def test_reconcile_reverifies_worker_digest_at_decision_time(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    doc.saved_snap = (1, 2)
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: None
    panel._doc_text = lambda d: "text\n"
    panel._reconcile_failure_dialog = lambda problems: None
    digests = []

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 2))
    monkeypatch.setattr(panelide.ide_branch_sync, "file_digest",
                        lambda p: digests.append(p) or "digest")

    safe = panel._reconcile_docs_after_branch(
        [(doc, path, "digest", (1, 2), "digest")])

    assert safe == {doc.buffer}
    assert digests == [path]
    assert doc.saved_snap == (1, 2)
    assert doc.conflict is False


def test_clean_doc_with_stale_editor_snapshot_reloads(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    doc.dirty = False
    doc.saved_snap = (1, 1)
    reloaded = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: None
    panel._doc_text = lambda d: "text\n"
    panel._reconcile_failure_dialog = lambda problems: None
    panel.reload_buffer = lambda buf, p: (
        reloaded.append(p), doc.resolve_reload(), True)[2]

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 2))

    safe = panel._reconcile_docs_after_branch(
        [(doc, path, "digest", (1, 2), "digest")])

    assert safe == {doc.buffer}
    assert reloaded == [path]


def test_conflict_keep_explicitly_allows_resume(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    panel = _panel()
    panel._branch_op = True
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._doc_text = lambda d: "text\n"
    panel._reconcile_failure_dialog = lambda problems: set()
    panel._conflict_dialog = lambda d: (d.resolve_keep_local(), "keep")[1]

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 3))

    safe = panel._reconcile_docs_after_branch(
        [(doc, path, "digest", (1, 2), "digest")])

    assert safe == {doc.buffer}
    assert doc.conflict is False


def test_dirty_doc_with_stale_editor_snapshot_gets_conflict(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    doc.saved_snap = (1, 1)  # editor baseline predates an external write
    conflicts = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: conflicts.append(d)
    panel._doc_text = lambda d: "text\n"
    panel._reconcile_failure_dialog = lambda problems: None

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 2))
    monkeypatch.setattr(panelide.ide_branch_sync, "file_digest",
                        lambda p: "digest")

    safe = panel._reconcile_docs_after_branch(
        [(doc, path, "digest", (1, 2), "digest")])

    assert safe == set()
    assert doc.conflict is True
    assert conflicts == [doc]
    assert doc.saved_snap == (1, 1)


def test_stale_worker_snapshot_does_not_resume_dirty_buffer(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    conflicts = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: conflicts.append(d)
    panel._doc_text = lambda d: "text\n"
    panel._reconcile_failure_dialog = lambda problems: None

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 3))
    monkeypatch.setattr(panelide.ide_branch_sync, "file_digest",
                        lambda p: (_ for _ in ()).throw(
                            AssertionError("stale digest must not be used")))

    safe = panel._reconcile_docs_after_branch(
        [(doc, path, "digest", (1, 2), "digest")])

    assert safe == set()
    assert doc.conflict is True
    assert doc.saved_snap is None
    assert conflicts == [doc]


def test_digest_failure_leaves_document_unsafe(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    doc.saved_snap = (1, 2)
    problems = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: None
    panel._doc_text = lambda d: "text\n"
    panel._reconcile_failure_dialog = lambda items: problems.extend(items)

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 2))
    monkeypatch.setattr(panelide.ide_branch_sync, "file_digest",
                        lambda p: None)

    safe = panel._reconcile_docs_after_branch(
        [(doc, path, "digest", (1, 2), "digest")])

    assert safe == set()
    assert doc.unsafe is True
    assert doc.conflict is True
    assert problems and problems[0][0] is doc
    panel._resume_docs_after_branch([(doc, path, "digest", (1, 2), "digest")],
                                    safe)
    assert doc.resumed == 0


def test_stat_exception_leaves_document_unsafe(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    problems = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: None
    panel._doc_text = lambda d: "text\n"
    panel._reconcile_failure_dialog = lambda items: problems.extend(items)

    def broken(path):
        raise OSError("stat failed")

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot", broken)

    safe = panel._reconcile_docs_after_branch([(doc, path, "digest")])

    assert safe == set()
    assert doc.unsafe is True
    assert "reconciliation failed" in doc.unsafe_reason
    assert problems and problems[0][0] is doc


def test_stale_clean_snapshot_reloads_the_current_file(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    doc.dirty = False
    reloaded = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: None
    panel._doc_text = lambda d: "text\n"
    panel._reconcile_failure_dialog = lambda problems: None
    panel.reload_buffer = lambda buf, p: reloaded.append(p) or True

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 4))

    safe = panel._reconcile_docs_after_branch(
        [(doc, path, None, (1, 2), None)])

    assert safe == {doc.buffer}
    assert reloaded == [path]


def test_strict_mode_pauses_dirty_doc_without_pre_digest(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    doc.saved_snap = (1, 2)
    problems = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: None
    panel._doc_text = lambda d: "text\n"
    panel._reconcile_failure_dialog = lambda items: problems.extend(items)

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 2))
    monkeypatch.setattr(panelide.ide_branch_sync, "file_digest",
                        lambda p: (_ for _ in ()).throw(
                            AssertionError("no digest expected")))

    safe = panel._reconcile_docs_after_branch([(doc, path, None)],
                                              strict=True)

    assert safe == set()
    assert doc.unsafe is True
    assert problems and problems[0][0] is doc


def test_create_branch_worker_snapshots_open_documents(tmp_path, monkeypatch):
    doc = _Doc(str(tmp_path / "file.txt"))
    calls = []
    panel = _panel()
    panel.root = str(tmp_path)
    panel._branch_op = False
    panel._shutdown = False
    panel._cancel_pending_creation = lambda: None
    panel._pause_docs_for_branch = lambda: [(doc, doc.path)]
    panel._snapshot_docs_after_branch = (
        lambda prepared: calls.append(("snapshot", len(prepared))) or prepared)
    panel._branch_done = lambda *args: calls.append(("done",) + args)
    panel.branch_lbl = _Label()
    panel.branch_btn = _Button()

    original = threading.Thread

    class InlineThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            self.target()

    threading.Thread = InlineThread
    try:
        monkeypatch.setattr(panelide.ide_git, "create_branch",
                            lambda root, name: (True, "ok"))
        monkeypatch.setattr(panelide.GLib, "idle_add",
                            lambda func, *args: calls.append(
                                ("idle", func, args)))
        panel._create_branch("feature")
    finally:
        threading.Thread = original

    assert ("snapshot", 1) in calls
    idle = [item for item in calls if item[0] == "idle"]
    assert idle and idle[0][1] is panel._branch_done


def test_branch_done_reconciles_create_and_resumes_only_safe_docs():
    doc = _Doc("/repo/file.txt")
    calls = []
    panel = _panel()
    panel._shutdown = False
    panel._branch_op = True
    panel.docs = {doc.buffer: doc}
    panel._reconcile_docs_after_branch = (
        lambda prepared, strict=False: calls.append(
            ("reconcile", strict, len(prepared))) or {doc.buffer})
    panel._resume_docs_after_branch = (
        lambda prepared, safe: calls.append(("resume", safe)))
    panel._invalidate_branch_info = lambda: None
    panel._refresh_after_branch = lambda: calls.append(("refresh",))
    panel._branch_error_dialog = lambda *a: calls.append(("error",))
    panel.branch_btn = _Button()

    prepared = [(doc, doc.path, "digest", (1, 2), "digest")]
    panel._branch_done(True, "", "feature", "create", prepared)

    assert ("reconcile", True, 1) in calls
    assert ("resume", {doc.buffer}) in calls
    assert ("refresh",) in calls
    assert panel._branch_op is False


def test_branch_done_failure_marks_every_doc_unsafe_and_resumes_nothing():
    doc = _Doc("/repo/file.txt")
    calls = []
    panel = _panel()
    panel._shutdown = False
    panel._branch_op = True
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._reconcile_docs_after_branch = (
        lambda prepared, strict=False: (_ for _ in ()).throw(
            RuntimeError("boom")))
    panel._reconcile_failure_dialog = lambda problems: calls.append(
        ("problems", len(problems)))
    panel._resume_docs_after_branch = (
        lambda prepared, safe: calls.append(("resume", safe)))
    panel._invalidate_branch_info = lambda: None
    panel._refresh_after_branch = lambda: calls.append(("refresh",))
    panel.branch_btn = _Button()

    panel._branch_done(True, "", "feature", "switch",
                       [(doc, doc.path, "digest")])

    assert doc.unsafe is True
    assert ("resume", set()) in calls
    assert ("problems", 1) in calls
    assert panel._branch_op is False


def test_autosave_refuses_to_overwrite_newer_disk_content(monkeypatch):
    doc = _Doc("/repo/file.txt")
    doc.saved_snap = (1, 2)
    saved = []
    conflicts = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: conflicts.append(d)
    panel.save_buffer = lambda buf: saved.append(buf)
    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 3))

    panel._autosave_buffer(doc.buffer)

    assert saved == []
    assert doc.conflict is True
    assert conflicts == [doc]


def test_autosave_writes_when_disk_still_matches(monkeypatch):
    doc = _Doc("/repo/file.txt")
    doc.saved_snap = (1, 2)
    saved = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: None
    panel.save_buffer = lambda buf: saved.append(buf)
    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 2))

    panel._autosave_buffer(doc.buffer)

    assert saved == [doc.buffer]


def test_autosave_callback_never_writes_conflicted_or_unsafe_or_clean_docs():
    for setup in ("conflict", "unsafe", "clean"):
        doc = _Doc("/repo/file.txt")
        doc.saved_snap = (1, 2)
        if setup == "conflict":
            doc.mark_conflict()
        elif setup == "unsafe":
            doc.mark_unsafe("disk not verified")
        else:
            doc.dirty = False
        saved = []
        panel = _panel()
        panel._branch_op = False
        panel.docs = {doc.buffer: doc}
        panel._update_tab_ui = lambda buf: None
        panel._conflict_dialog = lambda d: None
        panel.save_buffer = lambda buf: saved.append(buf)

        panel._autosave_buffer(doc.buffer)

        assert saved == [], setup


def test_save_buffer_refuses_conflicted_unsafe_and_external_change(monkeypatch):
    for setup in ("conflict", "unsafe", "external"):
        doc = _Doc("/repo/file.txt")
        doc.saved_snap = (1, 2)
        if setup == "conflict":
            doc.mark_conflict()
        elif setup == "unsafe":
            doc.mark_unsafe("disk not verified")
        writes = []
        panel = _panel()
        panel._branch_op = False
        panel.docs = {doc.buffer: doc}
        panel._update_tab_ui = lambda buf: None
        monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                            lambda p, setup=setup: (
                                (1, 3) if setup == "external" else (1, 2)))
        monkeypatch.setattr(panelide, "atomic_write",
                            lambda path, text: writes.append((path, text)))

        assert panel.save_buffer(doc.buffer) is False
        assert writes == []
        if setup == "external":
            assert doc.conflict is True


def test_ctrl_s_with_conflict_requires_confirmation_and_never_writes(
        tmp_path, monkeypatch):
    doc = _Doc(str(tmp_path / "file.txt"))
    doc.mark_conflict()
    widget = object()
    saved = []
    confirmed = []
    panel = _panel()
    panel._branch_op = False
    panel.ed_tabs = _Tabs(widget)
    panel.ed_paths = {doc.path: (doc.buffer, widget)}
    panel.docs = {doc.buffer: doc}
    panel._confirm_save_conflict = lambda d: confirmed.append(d) or False
    panel.save_buffer = lambda buf: saved.append(buf) or True
    panel.get_toplevel = lambda: None
    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 2))

    panel.save_file()

    assert confirmed == [doc]
    assert saved == []
    assert doc.conflict is True


def test_ctrl_s_explicit_consent_saves_local_version(tmp_path, monkeypatch):
    doc = _Doc(str(tmp_path / "file.txt"))
    doc.mark_conflict()
    widget = object()
    saved = []
    panel = _panel()
    panel._branch_op = False
    panel.ed_tabs = _Tabs(widget)
    panel.ed_paths = {doc.path: (doc.buffer, widget)}
    panel.docs = {doc.buffer: doc}
    panel._confirm_save_conflict = (
        lambda d: (d.resolve_keep_local(), True)[1])
    panel.save_buffer = lambda buf: saved.append(buf) or True
    panel.get_toplevel = lambda: None
    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 2))

    panel.save_file()

    assert saved == [doc.buffer]
    assert doc.conflict is False


def test_reload_failure_leaves_document_unsafe(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    doc.dirty = False
    doc.saved_snap = (1, 2)
    problems = []
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: None
    panel._doc_text = lambda d: "old\n"
    panel._reconcile_failure_dialog = lambda items: problems.extend(items)
    panel.reload_buffer = lambda buf, p: False

    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 3))

    safe = panel._reconcile_docs_after_branch(
        [(doc, path, None, (1, 2), None)])

    assert safe == set()
    assert doc.unsafe is True
    assert doc.conflict is True
    assert problems and problems[0][0] is doc


def test_ctrl_s_on_deleted_doc_offers_recovery_not_silent_noop(tmp_path):
    doc = _Doc(str(tmp_path / "file.txt"))
    doc.deleted = True
    widget = object()
    called = []
    saved = []
    panel = _panel()
    panel._branch_op = False
    panel.ed_tabs = _Tabs(widget)
    panel.ed_paths = {doc.path: (doc.buffer, widget)}
    panel.docs = {doc.buffer: doc}
    panel._deleted_save_recovery = lambda d: called.append(d) or True
    panel.save_buffer = lambda buf: saved.append(buf) or True

    panel.save_file()

    assert called == [doc]
    assert saved == []
    assert doc.deleted is True


def test_recreate_deleted_doc_never_overwrites_reappeared_file(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("newer disk version\n", encoding="utf-8")
    doc = _Doc(str(path))
    doc.deleted = True
    refreshed = []
    panel = _panel()
    panel._doc_text = lambda d: "editor version\n"
    panel.refresh_tree = lambda: refreshed.append(True)
    panel._update_tab_ui = lambda buf: None

    result = panel._recreate_deleted_doc(doc)

    assert result == "exists"
    assert path.read_text(encoding="utf-8") == "newer disk version\n"
    assert doc.deleted is True
    assert refreshed == []


def test_recreate_deleted_doc_creates_exclusively_when_absent(tmp_path):
    path = tmp_path / "file.txt"
    doc = _Doc(str(path))
    doc.deleted = True
    refreshed = []
    panel = _panel()
    panel._doc_text = lambda d: "editor version\n"
    panel.refresh_tree = lambda: refreshed.append(True)
    panel._update_tab_ui = lambda buf: None

    result = panel._recreate_deleted_doc(doc)

    assert result == "ok"
    assert path.read_text(encoding="utf-8") == "editor version\n"
    assert doc.deleted is False
    assert refreshed == [True]


def test_close_deleted_recreate_race_aborts_without_overwrite(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("disk\n", encoding="utf-8")
    doc = _Doc(str(path))
    doc.deleted = True
    panel = _panel()
    panel._doc_text = lambda d: "editor\n"
    panel._deleted_dialog = lambda d: panelide.Gtk.ResponseType.YES
    panel._resolve_reappeared_deleted = lambda d: "cancel"

    assert panel._try_close_doc(doc, doc.path) == "abort"
    assert path.read_text(encoding="utf-8") == "disk\n"


def test_save_as_confirms_overwrite_and_handles_creation_race(
        tmp_path, monkeypatch):
    target = tmp_path / "target.txt"
    doc = _Doc(str(tmp_path / "source.txt"))
    races = []

    class _Chooser:
        def __init__(self, *args, **kwargs):
            self.confirm = False
            self.name = None

        def add_buttons(self, *args):
            pass

        def set_do_overwrite_confirmation(self, value):
            self.confirm = value

        def set_current_name(self, name):
            self.name = name

        def run(self):
            return panelide.Gtk.ResponseType.OK

        def get_filename(self):
            return str(target)

        def destroy(self):
            pass

    panel = _panel()
    panel.get_toplevel = lambda: None
    panel._doc_text = lambda d: "editor\n"
    panel._update_tab_ui = lambda buf: None
    panel.refresh_tree = lambda: None
    panel.open_widgets = {}
    panel.ed_paths = {}
    panel._save_as_race_dialog = lambda path, changed: races.append(
        (path, changed))

    chooser = _Chooser()
    monkeypatch.setattr(panelide.Gtk, "FileChooserDialog",
                        lambda *a, **kw: chooser)
    monkeypatch.setattr(panelide, "atomic_create",
                        lambda path, text: (_ for _ in ()).throw(
                            FileExistsError(path)))

    assert panel._save_as_doc(doc) is False
    assert chooser.confirm is True
    assert races == [(str(target), False)]
    assert doc.path == str(tmp_path / "source.txt")


def test_save_as_overwrites_only_after_confirmation_and_state_check(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    doc = _Doc(str(tmp_path / "source.txt"))

    class _Chooser:
        def __init__(self, *args, **kwargs):
            pass

        def add_buttons(self, *args):
            pass

        def set_do_overwrite_confirmation(self, value):
            self.confirm = value

        def set_current_name(self, name):
            pass

        def run(self):
            return panelide.Gtk.ResponseType.OK

        def get_filename(self):
            return str(target)

        def destroy(self):
            pass

    panel = _panel()
    panel.get_toplevel = lambda: None
    panel._doc_text = lambda d: "editor\n"
    panel._update_tab_ui = lambda buf: None
    panel.refresh_tree = lambda: None
    panel.open_widgets = {}
    panel.ed_paths = {}
    panel._save_as_race_dialog = lambda path, changed: None

    original = panelide.Gtk.FileChooserDialog
    panelide.Gtk.FileChooserDialog = lambda *a, **kw: _Chooser()
    try:
        assert panel._save_as_doc(doc) is True
    finally:
        panelide.Gtk.FileChooserDialog = original

    assert target.read_text(encoding="utf-8") == "editor\n"
    assert doc.path == str(target)


def test_deleted_save_recovery_handles_reappearance(monkeypatch):
    class _Dialog:
        def __init__(self, *args, **kwargs):
            pass

        def add_button(self, label, response):
            return _Button()

        def set_default_response(self, response):
            pass

        def run(self):
            return panelide.Gtk.ResponseType.YES

        def destroy(self):
            pass

    doc = _Doc("/repo/file.txt")
    doc.deleted = True
    resolved = []
    panel = _panel()
    panel.get_toplevel = lambda: None
    panel._recreate_deleted_doc = lambda d: "exists"
    panel._resolve_reappeared_deleted = lambda d: resolved.append(d) or "cancel"
    monkeypatch.setattr(panelide.Gtk, "MessageDialog", _Dialog)

    assert panel._deleted_save_recovery(doc) is False
    assert resolved == [doc]


def test_save_as_changed_during_write_is_not_overwritten(tmp_path, monkeypatch):
    target = tmp_path / "target.txt"
    target.write_text("newer\n", encoding="utf-8")
    doc = _Doc(str(tmp_path / "source.txt"))
    races = []

    class _Chooser:
        def __init__(self, *args, **kwargs):
            pass

        def add_buttons(self, *args):
            pass

        def set_do_overwrite_confirmation(self, value):
            pass

        def set_current_name(self, name):
            pass

        def run(self):
            return panelide.Gtk.ResponseType.OK

        def get_filename(self):
            return str(target)

        def destroy(self):
            pass

    panel = _panel()
    panel.get_toplevel = lambda: None
    panel._doc_text = lambda d: "editor\n"
    panel._update_tab_ui = lambda buf: None
    panel.refresh_tree = lambda: None
    panel.open_widgets = {}
    panel.ed_paths = {}
    panel._save_as_race_dialog = lambda path, changed: races.append(
        (path, changed))

    monkeypatch.setattr(panelide.Gtk, "FileChooserDialog",
                        lambda *a, **kw: _Chooser())
    monkeypatch.setattr(panelide, "atomic_write_checked",
                        lambda path, text, expected: (_ for _ in ()).throw(
                            panelide.FileChangedError("changed")))

    assert panel._save_as_doc(doc) is False
    assert races == [(str(target), True)]
    assert target.read_text(encoding="utf-8") == "newer\n"
    assert doc.path == str(tmp_path / "source.txt")


def test_reconcile_failure_dialog_keeps_paused_by_default(monkeypatch):
    class _Dialog:
        def __init__(self, *args, **kwargs):
            self.response = panelide.Gtk.ResponseType.CANCEL

        def add_button(self, label, response):
            if response == panelide.Gtk.ResponseType.CANCEL:
                self.response = response
            return _Button()

        def set_default_response(self, response):
            self.response = response

        def run(self):
            return self.response

        def destroy(self):
            pass

    doc = _Doc("/repo/file.txt")
    doc.mark_unsafe("unverified")
    panel = _panel()
    panel.docs = {doc.buffer: doc}
    panel.get_toplevel = lambda: None
    panel._update_tab_ui = lambda buf: None
    monkeypatch.setattr(panelide.Gtk, "MessageDialog", _Dialog)

    panel._reconcile_failure_dialog([(doc, "unverified")])

    assert doc.unsafe is True
    assert doc.conflict is True
    assert doc.resumed == 0


def test_reconcile_failure_dialog_can_reload_or_keep_explicitly(monkeypatch):
    class _Dialog:
        response = panelide.Gtk.ResponseType.YES

        def __init__(self, *args, **kwargs):
            pass

        def add_button(self, label, response):
            return _Button()

        def set_default_response(self, response):
            pass

        def run(self):
            return type(self).response

        def destroy(self):
            pass

    doc = _Doc("/repo/file.txt")
    doc.mark_unsafe("unverified")
    reloaded = []
    panel = _panel()
    panel.docs = {doc.buffer: doc}
    panel.get_toplevel = lambda: None
    panel._update_tab_ui = lambda buf: None
    panel.reload_buffer = lambda buf, path: (
        reloaded.append(path), doc.resolve_reload(), True)[2]
    monkeypatch.setattr(panelide.Gtk, "MessageDialog", _Dialog)

    keep = panel._reconcile_failure_dialog([(doc, "unverified")])
    assert reloaded == [doc.path]
    assert doc.unsafe is False
    assert keep == set()

    doc.mark_unsafe("unverified again")
    doc.dirty = True
    _Dialog.response = panelide.Gtk.ResponseType.NO
    keep = panel._reconcile_failure_dialog([(doc, "unverified again")])
    assert keep == {doc.buffer}
    assert doc.unsafe is False
    assert doc.conflict is False
    assert doc.resumed == 1


def test_do_refresh_forces_the_nested_repository_that_changed(tmp_path):
    class _Store:
        def get_iter_first(self):
            return None

        def clear(self):
            pass

    class _Selection:
        def get_selected(self):
            return (None, None)

    class _Tree:
        def get_selection(self):
            return _Selection()

    root = str(tmp_path / "repo")
    nested = os.path.join(root, "vendor", "lib")
    calls = []
    panel = _panel()
    panel.root = root
    panel.store = _Store()
    panel.tree = _Tree()
    panel._branch_op = False
    panel._refresh_id = None
    panel._pending = None
    panel._nested_roots = {os.path.normpath(nested)}
    panel._force_state_roots = {os.path.normpath(nested)}
    panel._worktree_state = {"root": root}
    panel._worktree_state_for = lambda path, force=False: calls.append(
        (path, force))
    panel.populate = lambda *a: None

    panel._do_refresh()

    assert (os.path.normpath(nested), True) in calls
    assert (os.path.normpath(root), False) in calls
    assert panel._force_state_roots == set()


def test_external_reconcile_does_not_hash_buffers_on_gui(tmp_path, monkeypatch):
    path = str(tmp_path / "open.txt")
    doc = _Doc(path)
    doc.saved_snap = (1, 2)
    panel = _panel()
    panel._branch_op = False
    panel.docs = {doc.buffer: doc}
    panel._update_tab_ui = lambda buf: None
    panel._conflict_dialog = lambda d: None
    panel._doc_text = lambda d: "text\n"

    def forbidden(*args, **kwargs):
        raise AssertionError("external reconcile must not hash on the GUI thread")

    monkeypatch.setattr(panelide.ide_branch_sync, "file_digest", forbidden)
    monkeypatch.setattr(panelide.ide_branch_sync, "disk_snapshot",
                        lambda p: (1, 2))

    panel._reconcile_docs_after_branch([(doc, path, None)])

    assert doc.saved_snap == (1, 2)


def test_state_owner_prefers_an_expanded_nested_repository(tmp_path):
    root = str(tmp_path / "repo")
    nested = os.path.join(root, "vendor", "lib")
    panel = _panel()
    panel.root = root
    panel._nested_roots = {os.path.normpath(nested)}
    panel._force_state_roots = set()

    assert panel._state_owner(os.path.join(nested, "src", "a.py")) == \
        os.path.normpath(nested)
    assert panel._state_owner(os.path.join(root, "src", "a.py")) == \
        os.path.normpath(root)

    panel._mark_state_dirty(os.path.join(nested, "src", "new.py"))
    assert panel._force_state_roots == {os.path.normpath(nested)}


class _Thread:
    def __init__(self, finish_on_join):
        self.alive = True
        self.finish_on_join = finish_on_join
        self.timeout = None

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.timeout = timeout
        if self.finish_on_join:
            self.alive = False


def _shutdown_panel(thread, branch_op=True):
    doc = _Doc("/repo/file.txt")
    saved = []
    panel = _panel()
    panel._shutdown = False
    panel._branch_thread = thread
    panel._branch_op = branch_op
    panel.docs = {doc.buffer: doc}
    panel.audio_state = {}
    panel.monitors = {}
    panel.players = []
    panel.harness_pid = None
    panel.cmd_terms = []
    panel.harness_term = _Term()
    panel.save_buffer = lambda buf: saved.append(buf)
    return panel, doc, saved


def test_shutdown_waits_for_the_full_switch_budget():
    thread = _Thread(finish_on_join=True)
    panel, doc, saved = _shutdown_panel(thread, branch_op=False)

    panel.shutdown()

    assert thread.timeout == panelide.ide_git.SWITCH_TIMEOUT + 5.0
    assert saved == [doc.buffer]


def test_shutdown_does_not_save_while_git_is_still_running():
    thread = _Thread(finish_on_join=False)
    panel, _doc, saved = _shutdown_panel(thread)

    panel.shutdown()

    assert saved == []


def test_shutdown_does_not_save_unreconciled_finished_branch():
    thread = _Thread(finish_on_join=True)
    panel, _doc, saved = _shutdown_panel(thread, branch_op=True)

    panel.shutdown()

    assert saved == []
