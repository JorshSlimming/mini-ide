"""Pure helpers for the multitask pane sizing contract (headless-testable).

The title width and split calculations stay independent from GTK so the
multitask layout can be verified without a display.
"""


# Max chars for the centered project title per column count. The GTK label
# must ellipsize (END) instead of overlapping buttons.
_TITLE_MAX = {1: 40, 2: 30, 3: 24}

# Minimum reasonable width per multitask column (px). Below this the
# terminal prompt starts wrapping and buttons truncate.
PANEL_MIN_PX = 300


def title_max_chars(n_projects):
    """Max title chars for N side-by-side projects (ellipsize, never overlap)."""
    try:
        n = int(n_projects)
    except (TypeError, ValueError):
        return 24
    if n in _TITLE_MAX:
        return _TITLE_MAX[n]
    if n <= 0:
        return 24
    return 18


def split_position(total_px, left_count, total_count, min_per_panel=PANEL_MIN_PX):
    """Equal-split pane position (pure version of PanelIDE._mt_sizes math).

    Returns int position, or None when total_px is too small to measure
    (caller must skip, as before). Minimum column width is enforced by the
    panel's own size request (PANEL_MIN_PX), not by shifting the split:
    an equal split already satisfies minimums whenever the window is wide
    enough (total >= count * min), and when it is not, Gtk honors the
    child's min size instead of squeezing content.
    """
    try:
        total = int(total_px)
        left = int(left_count)
        count = int(total_count)
    except (TypeError, ValueError):
        return None
    if total <= 50 or count <= 1 or left <= 0 or left >= count:
        return None
    return int(total * left / count)
