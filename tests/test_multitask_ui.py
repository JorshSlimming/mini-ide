"""PanelIDE multitask layout regressions (headless, no GTK/display)."""
import mini_ide.runners as R
from mini_ide import multitask_ui as MT


def test_runner_missing_has_explicit_no_runner_presentation():
    state, label, css_class, tip = R.presentation(
        {"has_runner": False, "root": "/x/projects-bot"})
    assert (state, label, css_class) == (
        "none", "— NO RUNNER", "runner-none")
    assert "projects-bot" in tip


def test_runner_status_has_consistent_full_presentation():
    info = {"has_runner": True, "unit": "u", "repo": "r"}
    state, label, css_class, tip = R.presentation(info, local="active")
    assert (state, label, css_class) == (
        "on", "● RUNNER ON", "runner-on")
    assert "r\nu" in tip
    assert "Click to turn off." in tip

    state, label, css_class, tip = R.presentation(info, local="inactive")
    assert (state, label, css_class) == (
        "off", "○ RUNNER OFF", "runner-off")
    assert "Click to turn on." in tip


def test_runner_busy_and_wait_keep_semantic_labels():
    info = {"has_runner": True, "repo": "r"}
    busy = R.presentation(info, state="busy")
    waiting = R.presentation(info, state="wait")
    assert busy[:3] == ("busy", "◐ RUNNER BUSY", "runner-busy")
    assert waiting[:3] == ("wait", "… RUNNER …", "runner-wait")


def test_runner_presentation_compact_labels():
    info = {"has_runner": True, "repo": "r"}
    expected = (
        ("on", "● ON", "runner-on"),
        ("off", "○ OFF", "runner-off"),
        ("busy", "◐ BUSY", "runner-busy"),
        ("wait", "… WAIT", "runner-wait"),
        ("none", "— NONE", "runner-none"),
    )
    for state, label, css_class in expected:
        presented = R.presentation(
            info, state=state, compact=True)
        assert presented[:3] == (state, label, css_class)

    missing = R.presentation(
        {"has_runner": False, "root": "/tmp/project"}, compact=True)
    assert missing[:3] == ("none", "— NONE", "runner-none")


def test_title_max_chars():
    assert MT.title_max_chars(1) == 40
    # Narrow columns: titles yield space before project-bar buttons do.
    assert MT.title_max_chars(2) == 12
    assert MT.title_max_chars(3) == 8
    assert MT.title_max_chars(5) == 18
    assert MT.title_max_chars("bogus") == 24


def test_split_position_equal():
    assert MT.split_position(1920, 1, 3) == 640
    assert MT.split_position(1920, 2, 3) == 1280
    assert MT.split_position(1200, 1, 2) == 600
    # Narrow window: still equal split; Gtk min-size (PANEL_MIN_PX)
    # prevents squeezing instead of shifting the divider.
    assert MT.split_position(600, 1, 3) == 200


def test_split_position_small_skipped():
    assert MT.split_position(40, 1, 3) is None
    assert MT.split_position(0, 1, 2) is None


def test_global_files_action_predicts_next_toggle():
    assert MT.global_files_action([]) == "Show all files"
    assert MT.global_files_action([False, False]) == "Hide all files"
    assert MT.global_files_action([True, True]) == "Show all files"
    assert MT.global_files_action([False, True]) == "Show all files"
    assert MT.global_files_action([True, False, True]) == "Show all files"


def test_compact_bottom_visible_needs_both_collapsed():
    assert MT.compact_bottom_visible(False, False) is True
    assert MT.compact_bottom_visible(True, False) is True
    assert MT.compact_bottom_visible(False, True) is True
    assert MT.compact_bottom_visible(True, True) is False


def test_compact_bottom_position_tracks_collapses_and_saved_split():
    assert MT.compact_bottom_position(800, False, False) == 280
    assert MT.compact_bottom_position(800, False, False, 314) == 314
    assert MT.compact_bottom_position(800, True, False, 314) == 0
    assert MT.compact_bottom_position(800, False, True, 314) == 800
    assert MT.compact_bottom_position(800, True, True, 314) is None
    assert MT.compact_bottom_position(40, False, False, 20) is None
    assert MT.compact_bottom_position(800, False, False, 900) == 280


def test_compact_main_position_keeps_single_panel():
    assert MT.compact_main_position(1000, False, False) == 580
    assert MT.compact_main_position(1000, True, False) == 580
    assert MT.compact_main_position(1000, False, True) == 580
    assert MT.compact_main_position(1000, True, True) == 1000
    assert MT.compact_main_position(40, False, False) is None
