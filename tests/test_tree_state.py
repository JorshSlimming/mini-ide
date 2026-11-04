"""Tests for tree visibility and local-content classification (no GTK)."""
import os

from mini_ide import tree_state as T


def _state(**overrides):
    state = {
        "root": "/repo",
        "tracked": set(),
        "untracked": set(),
        "ignored": set(),
        "untracked_dirs": set(),
        "ignored_dirs": set(),
    }
    state.update(overrides)
    return state


def test_scan_directory_shows_dotfiles_but_not_vcs_metadata(tmp_path):
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / "visible.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "folder").mkdir()

    listing = T.scan_directory(str(tmp_path))

    names = [e.name for e in listing.entries]
    assert ".env" in names
    assert ".git" not in names
    assert names == ["folder", ".env", "visible.txt"]
    assert listing.nested is True


def test_scan_directory_nested_false_for_normal_folder(tmp_path):
    (tmp_path / "a").write_text("x\n", encoding="utf-8")
    listing = T.scan_directory(str(tmp_path))
    assert listing.nested is False


def test_scan_directory_missing_folder_is_safe(tmp_path):
    listing = T.scan_directory(str(tmp_path / "missing"))
    assert listing.entries == []
    assert listing.nested is False


def test_dir_metadata_distinguishes_empty_and_nested(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / ".git").mkdir()
    normal = tmp_path / "normal"
    normal.mkdir()
    (normal / ".env").write_text("x\n", encoding="utf-8")

    assert T.dir_metadata(str(empty)) == (True, False)
    assert T.dir_metadata(str(nested)) == (False, True)
    assert T.dir_metadata(str(normal)) == (False, False)


def test_under_any_respects_path_components():
    roots = {os.path.normpath("/repo/brokerin")}
    assert T.under_any("/repo/brokerin", roots)
    assert T.under_any("/repo/brokerin/archivos/.gitkeep", roots)
    assert not T.under_any("/repo/brokerin2", roots)
    assert not T.under_any("/repo/brokerin-old/file", roots)


def test_needs_reclassification_only_accepts_covered_paths():
    state = _state(
        tracked={os.path.normpath("/repo/src"),
                 os.path.normpath("/repo/src/a.py")},
        untracked={os.path.normpath("/repo/new-folder")},
        ignored={os.path.normpath("/repo/cache")},
    )
    assert not T.needs_reclassification(state, "/repo/src/a.py")
    assert not T.needs_reclassification(state, "/repo/new-folder/deep/file")
    assert not T.needs_reclassification(state, "/repo/cache/obj.bin")
    assert T.needs_reclassification(state, "/repo/just-created.txt")
    assert T.needs_reclassification(None, "/repo/tracked.py")


def test_local_summary_counts_items_not_paths():
    state = _state(
        untracked={os.path.normpath("/repo/build"),
                   os.path.normpath("/repo/notes.txt")},
        ignored={os.path.normpath("/repo/.cache")},
    )
    compact = T.local_summary(state, compact=True)
    full = T.local_summary(state)
    assert T.local_counts(state) == (2, 1)
    assert "2 untracked" in compact
    assert "1 ignored" in compact
    assert "item(s)" in compact
    assert "whole folder counts as one item" in full
    assert T.local_summary(_state()) == ""


def test_ignore_rule_files_trigger_reclassification():
    assert T.affects_classification("/repo/.gitignore")
    assert T.affects_classification("/repo/sub/.gitmodules")
    assert not T.affects_classification("/repo/.env")
    assert not T.affects_classification("/repo/src/main.py")


def test_tracked_file_has_no_badge():
    state = _state(tracked={os.path.normpath("/repo/a.txt")})
    status = T.classify("/repo/a.txt", False, state)
    assert status.code == T.TRACKED
    assert status.label == ""
    assert status.local is False


def test_untracked_file_and_ignored_file_are_marked():
    state = _state(
        untracked={os.path.normpath("/repo/.env")},
        ignored={os.path.normpath("/repo/local.log")},
    )
    untracked = T.classify("/repo/.env", False, state)
    ignored = T.classify("/repo/local.log", False, state)
    assert untracked.code == T.UNTRACKED
    assert untracked.label == "untracked"
    assert "stays on disk" in untracked.tooltip
    assert "Hidden name" in untracked.tooltip
    assert ignored.code == T.IGNORED
    assert ignored.label == "ignored"


def test_collapsed_untracked_directory_marks_descendants():
    state = _state(untracked={os.path.normpath("/repo/brokerin")})
    status = T.classify("/repo/brokerin/archivos", True, state)
    assert status.code == T.UNTRACKED
    assert status.local is True


def test_empty_directory_is_marked_even_when_untracked():
    state = _state(untracked={os.path.normpath("/repo/logs")})
    status = T.classify("/repo/logs", True, state, empty=True)
    assert status.code == T.EMPTY
    assert status.label == "empty"
    assert "Git cannot track empty folders" in status.tooltip


def test_mixed_directory_has_tracked_and_local_content():
    state = _state(
        tracked={os.path.normpath("/repo/src"),
                 os.path.normpath("/repo/src/a.py")},
        untracked_dirs={os.path.normpath("/repo/src")},
    )
    status = T.classify("/repo/src", True, state)
    assert status.code == T.MIXED
    assert status.label == "mixed"


def test_directory_with_only_ignored_content():
    state = _state(ignored_dirs={os.path.normpath("/repo/cache")})
    status = T.classify("/repo/cache", True, state)
    assert status.code == T.IGNORED


def test_nested_repository_is_not_called_empty():
    status = T.classify("/repo/vendor/lib", True, _state(), nested=True)
    assert status.code == T.NESTED
    assert status.label == "repo"
    assert "separate Git repository" in status.tooltip


def test_unknown_entry_is_not_falsely_untracked():
    state = _state()
    status = T.classify("/repo/new-file", False, state)
    assert status.code == T.UNKNOWN
    assert status.label == "?"
    assert "could not classify" in status.tooltip


def test_unclassified_directory_is_not_falsely_called_local():
    status = T.classify("/repo/new-folder", True, _state())
    assert status.code == T.UNKNOWN
    assert status.label == "?"


def test_no_state_means_no_badge_and_no_false_claim():
    status = T.classify("/repo/.env", False, None)
    assert status.label == ""
    assert status.code == T.UNKNOWN
    assert "Hidden name" in status.tooltip


def test_hidden_tracked_file_keeps_tooltip_only():
    state = _state(tracked={os.path.normpath("/repo/.gitignore")})
    status = T.classify("/repo/.gitignore", False, state)
    assert status.code == T.TRACKED
    assert status.label == ""
    assert status.tooltip == "Hidden name (starts with '.')."
