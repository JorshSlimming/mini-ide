"""Pure helpers for the multitask pane sizing contract (headless-testable).

The title width and split calculations stay independent from GTK so the
multitask layout can be verified without a display.
"""


# Max chars for the centered project title per column count. The GTK label
# must ellipsize (END) instead of overlapping buttons.
_TITLE_MAX = {1: 40, 2: 12, 3: 8}

# Minimum reasonable width per multitask column (px). Below this the
# terminal prompt starts wrapping and buttons truncate.
PANEL_MIN_PX = 300

# Minimum usable editor width inside a multitask column (px). VTE keeps its
# own natural width, so Gtk must be allowed to overflow a too-narrow column
# rather than squeeze the editor into unreadable one-character wrapping.
PANEL_EDITOR_MIN_PX = 260

# Fixed GTK shrink budget for the two-pane project content (px). The editor
# and harness each need a usable minimum inside a 1600px window, so keep
# side-by-side columns from degenerating into wrapped one-character strips.
PANEL_TOP_MIN_PX = 170


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


def global_files_action(collapsed_states):
    """Label for the global Files toggle from per-project collapsed states.

    True means the project's tree is hidden. The label always predicts the
    next action: hide only when every tree is visible, otherwise show all.
    """
    states = list(collapsed_states or [])
    if states and all(not state for state in states):
        return "Hide all files"
    return "Show all files"


def compact_bottom_visible(tree_collapsed, tabs_collapsed):
    """Whether the compact bottom area stays visible.

    Files and Terminal collapse independently: only hide the whole strip
    when both are collapsed.
    """
    return not (bool(tree_collapsed) and bool(tabs_collapsed))


def compact_main_position(total_height, tree_collapsed, tabs_collapsed):
    """Vertical split for the compact top/bottom panes.

    Returns full height when the bottom area is hidden, else the 58% split.
    """
    try:
        height = int(total_height)
    except (TypeError, ValueError):
        return None
    if height <= 50:
        return None
    if bool(tree_collapsed) and bool(tabs_collapsed):
        return int(height)
    return int(height * 0.58)
