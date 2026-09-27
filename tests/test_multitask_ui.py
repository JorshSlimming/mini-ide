"""PanelIDE multitask layout regressions (headless, no GTK/display)."""
import mini_ide.runners as R
from mini_ide import multitask_ui as MT


def test_runner_missing_uses_quiet_state_and_repo_tooltip():
    state, css_class, tip = R.presentation(
        {"has_runner": False, "root": "/x/projects-bot"})
    assert state == "none"
    assert css_class == "runner-none"
    assert "projects-bot" in tip


def test_runner_status_maps_to_semantic_states():
    info = {"has_runner": True, "unit": "u", "repo": "r"}
    state, css_class, tip = R.presentation(info, local="active")
    assert (state, css_class) == ("on", "runner-on")
    assert "r\nu" in tip
    state, css_class, tip = R.presentation(info, local="inactive")
    assert (state, css_class) == ("off", "runner-off")
    assert "APAGADO" in tip


def test_title_max_chars():
    assert MT.title_max_chars(1) == 40
    assert MT.title_max_chars(2) == 30
    assert MT.title_max_chars(3) == 24
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
