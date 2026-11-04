"""Pure helpers for the project tree.

The tree reflects the real working tree. It must not hide user files just
because their names start with a dot, and it must explain which entries are
local-only (untracked, ignored, mixed) or empty folders that Git cannot
track. This module deliberately has no GTK dependency so the classification
rules can be unit-tested headlessly.
"""
import os
from collections import namedtuple

# Git metadata is not project content. Everything else, including dotfiles
# such as .env, .gitignore or .vscode, is shown to the user.
VCS_METADATA = frozenset({".git", ".hg", ".svn", ".bzr", "_darcs"})

Entry = namedtuple("Entry", "name path is_dir")
DirectoryListing = namedtuple("DirectoryListing", "entries nested")

EntryState = namedtuple("EntryState", "code label tooltip local")

TRACKED = "tracked"
UNTRACKED = "untracked"
IGNORED = "ignored"
EMPTY = "empty"
MIXED = "mixed"
LOCAL = "local"
NESTED = "nested"
UNKNOWN = "unknown"

_LABELS = {
    TRACKED: "",
    UNTRACKED: "untracked",
    IGNORED: "ignored",
    EMPTY: "empty",
    MIXED: "mixed",
    LOCAL: "local",
    NESTED: "repo",
    UNKNOWN: "?",
}

_TOOLTIPS = {
    TRACKED: "",
    UNTRACKED: ("Untracked by Git: exists only in the working tree. "
                "It stays on disk when you switch branches."),
    IGNORED: ("Ignored by Git: exists only in the working tree. "
              "It stays on disk when you switch branches."),
    EMPTY: ("Empty folder: Git cannot track empty folders, so it is not "
            "part of any branch. PanelIDE shows it; Git may replace it if "
            "the target branch has a file at the same path."),
    MIXED: ("Contains tracked files and local-only content "
            "(untracked or ignored). Local files stay on disk "
            "when you switch branches."),
    LOCAL: ("Local-only folder: it has no tracked files. "
            "Files in it stay on disk when you switch branches."),
    NESTED: ("Contains a separate Git repository. Its files are managed "
             "by that repository; the branch selector above belongs to "
             "the outer project."),
    UNKNOWN: ("Git could not classify this entry. It is shown from disk "
              "and was not modified."),
}

_HIDDEN_NOTE = "Hidden name (starts with '.')."

# Files whose contents change Git's ignore/submodule classification. A
# normal CHANGED event on a tracked file does not otherwise justify a new
# `git ls-files` scan, but these do.
CLASSIFICATION_FILES = frozenset({".gitignore", ".gitmodules"})


def affects_classification(path):
    """True when editing *path* can change tracked/ignored classification."""
    return os.path.basename(path) in CLASSIFICATION_FILES


def _safe_is_dir(entry):
    try:
        return entry.is_dir()
    except OSError:
        return False


def scan_directory(path):
    """Return visible entries plus whether *path* holds VCS metadata.

    Dotfiles are included; only VCS metadata directories/files are skipped
    because their contents are not project files. ``nested`` is True when
    this directory is the root of a nested repository, which lets callers
    classify its children with that repository's state instead of the
    outer project's state.
    """
    try:
        raw = list(os.scandir(path))
    except OSError:
        return DirectoryListing([], False)
    nested = any(e.name in VCS_METADATA for e in raw)
    entries = [Entry(e.name, e.path, _safe_is_dir(e))
               for e in raw if e.name not in VCS_METADATA]
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return DirectoryListing(entries, nested)


def dir_metadata(path):
    """Return ``(is_empty, has_vcs_metadata)`` without following recursion.

    ``has_vcs_metadata`` uses one stat per known metadata name, so it is
    reliable even when ``.git`` is not the first directory entry. Emptiness
    only needs the first entry, which keeps very large folders cheap.
    """
    nested = any(os.path.exists(os.path.join(path, name))
                 for name in VCS_METADATA)
    try:
        with os.scandir(path) as it:
            empty = next(it, None) is None
    except OSError:
        return False, False
    return empty, nested


def is_empty_dir(path):
    """True when *path* has no entries at all (including VCS metadata)."""
    return dir_metadata(path)[0]


def under_any(path, roots):
    """True when *path* is *roots* or lives below one of them.

    The comparison walks exact path components, so ``/repo/foo2`` is not
    considered inside ``/repo/foo``. This is important because Git reports
    collapsed untracked/ignored directories as prefixes.
    """
    if not roots:
        return False
    path = os.path.normpath(path)
    while True:
        if path in roots:
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def needs_reclassification(state, path):
    """True when *path* is not covered by the cached classification.

    The file monitor uses this to force a fresh ``git ls-files`` run when a
    new file or folder appears while the two-second cache is still valid.
    Without it a newly created entry could keep the ``?`` badge until some
    unrelated event triggered another refresh.
    """
    if not state:
        return True
    path = os.path.normpath(path)
    if (path in state.get("tracked", ())
            or path in state.get("untracked", ())
            or path in state.get("ignored", ())
            or path in state.get("untracked_dirs", ())
            or path in state.get("ignored_dirs", ())):
        return False
    if under_any(path, state.get("untracked", ())):
        return False
    if under_any(path, state.get("ignored", ())):
        return False
    return True


def local_counts(state):
    """Return ``(untracked, ignored)`` classification roots.

    ``worktree_state`` asks Git for ``--directory`` output, so a wholly
    untracked or ignored folder is one root. These are item counts, not
    file counts; callers must say so instead of presenting them as paths.
    """
    if not state:
        return (0, 0)
    return (len(state.get("untracked", ())),
            len(state.get("ignored", ())))


def local_summary(state, compact=False):
    """Human wording for the number of local-only classification roots.

    A collapsed folder counts as one item because Git did not enumerate
    its files. Returning an empty string means there is nothing to show.
    """
    untracked, ignored = local_counts(state)
    if not untracked and not ignored:
        return ""
    if compact:
        return "%d untracked · %d ignored item(s)" % (untracked, ignored)
    return ("%d untracked and %d ignored item(s) are local-only and stay "
            "on disk (a whole folder counts as one item)."
            % (untracked, ignored))


def _with_hidden(tooltip, hidden):
    if not hidden:
        return tooltip
    if tooltip:
        return tooltip + " " + _HIDDEN_NOTE
    return _HIDDEN_NOTE


def _state(code, hidden):
    return EntryState(code, _LABELS[code], _with_hidden(_TOOLTIPS[code], hidden),
                      code in (UNTRACKED, IGNORED, EMPTY, MIXED, LOCAL))


def classify(path, is_dir, state, empty=False, nested=False):
    """Classify one filesystem entry for display.

    ``state`` is the dict returned by :func:`mini_ide.git_state.worktree_state`
    or ``None`` when Git is unavailable. The function never guesses that an
    unclassified entry is local-only: it returns ``UNKNOWN`` instead, which
    avoids false "untracked" labels while a refresh is in progress.
    """
    path = os.path.normpath(path)
    hidden = os.path.basename(path).startswith(".")

    if not state:
        return EntryState(UNKNOWN, "", _with_hidden("", hidden), False)

    if nested:
        return _state(NESTED, hidden)

    tracked = path in state.get("tracked", ())
    untracked_root = under_any(path, state.get("untracked", ()))
    ignored_root = under_any(path, state.get("ignored", ()))
    untracked_here = (untracked_root
                      or path in state.get("untracked_dirs", ()))
    ignored_here = (ignored_root
                    or path in state.get("ignored_dirs", ()))

    if is_dir:
        if empty:
            return _state(EMPTY, hidden)
        if tracked:
            return _state(MIXED if (untracked_here or ignored_here)
                          else TRACKED, hidden)
        if untracked_here and ignored_here:
            return _state(LOCAL, hidden)
        if untracked_here:
            return _state(UNTRACKED, hidden)
        if ignored_here:
            return _state(IGNORED, hidden)
        # A non-tracked directory with no status entry is unusual (for
        # example a just-created folder or a stale classification). Do not
        # claim it is untracked or local; show it as unclassified.
        return _state(UNKNOWN, hidden)

    if tracked:
        return _state(TRACKED, hidden)
    if untracked_root:
        return _state(UNTRACKED, hidden)
    if ignored_root:
        return _state(IGNORED, hidden)
    return _state(UNKNOWN, hidden)
