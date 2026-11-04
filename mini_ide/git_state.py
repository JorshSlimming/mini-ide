"""Local Git branch helpers for the PanelIDE branch switcher.

Only local operations are used: inspecting HEAD, listing local branches, and
switching or creating branches. There is no network access and no GTK
dependency, so the module stays unit-testable.
"""
import os
import shutil
import subprocess

TIMEOUT = 8
SWITCH_TIMEOUT = 60


def _git(root, args, timeout=TIMEOUT):
    """Run a git command in *root*. Return CompletedProcess or None."""
    if not root or not os.path.isdir(root):
        return None
    exe = shutil.which("git")
    if not exe:
        return None
    env = os.environ.copy()
    # Never block the UI waiting for credentials or a terminal prompt.
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Read-only checks (status/ls-files) must not refresh the index and
    # contend with a switch for index.lock. Operations that need a lock
    # still take one.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            [exe, "-C", root, "-c", "core.quotepath=false"] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None


def _output(result):
    if result is None:
        return ""
    return (result.stderr or result.stdout or "").strip()


def repo_root(root):
    """Return the work-tree root of the repository containing *root*."""
    result = _git(root, ["rev-parse", "--show-toplevel"])
    if result is None or result.returncode != 0:
        return None
    top = result.stdout.strip()
    return top or None


def _current_branch(top):
    """Name of the branch HEAD points to, or None when detached."""
    result = _git(top, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    if result is not None and result.returncode == 0:
        return result.stdout.strip() or None
    return None


def snapshot(root, check_dirty=True):
    """Describe the current HEAD state of the repository containing *root*.

    ``check_dirty=False`` skips the ``git status`` scan. That scan is the
    only part that walks the working tree, so callers that only need the
    branch name (for example opening a menu) can stay responsive on a very
    large repository. The ``dirty`` key is then ``None`` (unknown).
    """
    top = repo_root(root)
    if not top:
        return {"is_repo": False, "root": None, "branch": None,
                "head": None, "detached": False, "unborn": False,
                "dirty": False}

    branch = _current_branch(top)
    head = None
    detached = False
    unborn = False
    if branch is None:
        detached = True
        result = _git(top, ["rev-parse", "--short", "HEAD"])
        if result is not None and result.returncode == 0:
            head = result.stdout.strip() or None
    else:
        # A fresh repository has a symbolic branch but no commit yet.
        # `git rev-parse --verify HEAD` fails until the first commit.
        result = _git(top, ["rev-parse", "--verify", "--quiet", "HEAD"])
        unborn = result is not None and result.returncode != 0

    dirty = None if not check_dirty else False
    if check_dirty:
        result = _git(top, ["status", "--porcelain", "--untracked-files=no"])
        if result is not None and result.returncode == 0:
            dirty = bool(result.stdout.strip())

    return {"is_repo": True, "root": top, "branch": branch, "head": head,
            "detached": detached, "unborn": unborn, "dirty": dirty}


def label(info):
    """Short human label for a snapshot."""
    if not info or not info.get("is_repo"):
        return ""
    if info.get("detached"):
        return "detached@%s" % (info.get("head") or "HEAD")
    return info.get("branch") or "HEAD"


def branches(root):
    """List local branches, most recently committed first.

    A repository with no commits yet has no ``refs/heads`` entry, but its
    symbolic HEAD is still a branch name the user can see and build on.
    Include it so the branch menu does not contradict the current label.
    """
    top = repo_root(root)
    if not top:
        return []
    result = _git(top, ["for-each-ref", "--sort=-committerdate",
                        "--format=%(refname:short)", "refs/heads"])
    if result is None or result.returncode != 0:
        return []
    names = [line.strip() for line in result.stdout.splitlines()
             if line.strip()]
    current = _current_branch(top)
    if current and current not in names:
        names.insert(0, current)
    return names


def _tracked_paths(top, pathspec=None):
    args = ["ls-files", "--cached", "--full-name", "-z"]
    if pathspec:
        args += pathspec
    result = _git(top, args)
    if result is None or result.returncode != 0:
        return None
    paths = set()
    for name in result.stdout.split("\0"):
        if not name:
            continue
        path = os.path.normpath(os.path.join(top, name))
        while path != top and path.startswith(top + os.sep):
            paths.add(path)
            path = os.path.dirname(path)
    return paths


def tracked_paths(root):
    """Return absolute indexed paths and their parents, or None on error.

    Directories not in this set contain no tracked files. Keep them visible:
    they may contain ignored files, untracked files, or empty directories.
    """
    top = repo_root(root)
    if not top:
        return None
    return _tracked_paths(top)


def _other_paths(top, extra_args, pathspec=None):
    """Absolute paths reported by ``git ls-files --others``.

    ``--directory`` collapses wholly untracked or ignored directories, so
    the result stays small in projects with large build/vendor trees.
    """
    args = (["ls-files", "--others", "--full-name", "--directory"]
            + list(extra_args) + ["-z"])
    if pathspec:
        args += pathspec
    result = _git(top, args)
    if result is None or result.returncode != 0:
        return None
    paths = set()
    for name in result.stdout.split("\0"):
        # Git appends "/" to collapsed directories. File names cannot end
        # in "/" on the supported platforms, so this is unambiguous.
        name = name.rstrip("/")
        if not name:
            continue
        paths.add(os.path.normpath(os.path.join(top, name)))
    return paths


def _ancestor_dirs(paths, top):
    """Every ancestor directory of *paths* inside the work tree."""
    dirs = set()
    for path in paths:
        parent = os.path.dirname(path)
        while parent != top and parent.startswith(top + os.sep):
            dirs.add(parent)
            parent = os.path.dirname(parent)
    return dirs


def _rebase_set(paths, source, target):
    """Move paths under *source* to *target*, dropping everything else.

    Git resolves symlinks in ``--show-toplevel``, while the tree keeps the
    path the user opened. Rebasing the classification to the caller's path
    avoids marking every entry as unknown when a project is opened through
    a symlink. Paths outside the opened subfolder are not needed by the
    tree and are dropped.
    """
    if source == target:
        return set(paths)
    out = set()
    prefix = source + os.sep
    for path in paths:
        if path == source:
            out.add(target)
        elif path.startswith(prefix):
            out.add(os.path.normpath(
                os.path.join(target, os.path.relpath(path, source))))
    return out


def worktree_state(root):
    """Classify the working tree for the file browser.

    Returns a dict with absolute paths, or ``None`` when *root* is not a
    Git repository or Git fails:

    ``tracked``
        Indexed files plus every parent directory that contains tracked
        content (the same shape as :func:`tracked_paths`).
    ``untracked`` / ``ignored``
        Paths reported by ``git ls-files --others``. A directory here
        means every descendant is local-only, so callers must treat it as
        a prefix, not just an exact path.
    ``untracked_dirs`` / ``ignored_dirs``
        Every ancestor directory of those roots. This is what lets the
        tree mark a directory that mixes tracked files with local files.

    Empty directories are not represented by Git; the tree detects them
    directly on disk. This function never mutates the repository.
    """
    top = repo_root(root)
    if not top:
        return None

    # Git reports the resolved repository path. If the caller opened a
    # symlink (or a subfolder of one), keep the caller's path so the tree's
    # absolute paths match the classification sets. Limiting the Git query
    # to an opened subfolder also keeps classification cheap in monorepos.
    base = os.path.normpath(os.path.abspath(root))
    real = os.path.realpath(base)
    pathspec = None
    if real != top and real.startswith(top + os.sep):
        rel = os.path.relpath(real, top)
        pathspec = ["--", ":(literal)" + rel]

    tracked = _tracked_paths(top, pathspec)
    if tracked is None:
        return None
    untracked = _other_paths(top, ["--exclude-standard"], pathspec)
    ignored = _other_paths(top, ["--ignored", "--exclude-standard"], pathspec)
    if untracked is None or ignored is None:
        return None

    dirs_top = top
    if real != base and (real == top or real.startswith(top + os.sep)):
        tracked = _rebase_set(tracked, real, base)
        untracked = _rebase_set(untracked, real, base)
        ignored = _rebase_set(ignored, real, base)
        dirs_top = base

    return {
        "root": top,
        "tracked": tracked,
        "untracked": untracked,
        "ignored": ignored,
        "untracked_dirs": _ancestor_dirs(untracked, dirs_top),
        "ignored_dirs": _ancestor_dirs(ignored, dirs_top),
    }


def validate_branch_name(root, name):
    """Validate a branch name using git's own rules. Return (ok, message)."""
    name = (name or "").strip()
    if not name:
        return False, "Enter a branch name."
    result = _git(root, ["check-ref-format", "--branch", name])
    if result is None:
        return False, "Git is not available."
    if result.returncode != 0:
        return False, "“%s” is not a valid branch name." % name
    return True, ""


def _unsupported_switch(message):
    low = (message or "").lower()
    return ("'switch' is not a git command" in low
            or "unknown subcommand" in low)


def _unsupported_no_overwrite_ignore(message):
    """True when Git knows ``switch`` but not its safety option."""
    low = (message or "").lower()
    if "no-overwrite-ignore" not in low:
        return False
    return any(part in low for part in
               ("unknown option", "unrecognized", "invalid option",
                "unknown switch"))


def _switch_result(root, args, name):
    result = _git(root, args, timeout=SWITCH_TIMEOUT)
    if result is None:
        return False, "Git is not available."
    if result.returncode == 0:
        return True, _output(result) or "Switched to branch “%s”." % name
    return False, _output(result) or "Could not switch to “%s”." % name


def switch_branch(root, name):
    """Switch to an existing local branch. Return (ok, message).

    ``--no-overwrite-ignore`` is deliberate: ignored files are user data
    too, and Git must stop instead of replacing them with tracked files
    from the target branch. Untracked files are already protected by
    Git's normal checkout safety.
    """
    name = (name or "").strip()
    ok, message = validate_branch_name(root, name)
    if not ok:
        return False, message
    ok, message = _switch_result(root, ["switch", "--no-overwrite-ignore", "--", name], name)
    if not ok and (_unsupported_switch(message)
                   or _unsupported_no_overwrite_ignore(message)):
        # Git older than 2.23 has no `switch`; checkout is the equivalent.
        # If only the safety option is missing, checkout still supports it
        # on every version that has `checkout --no-overwrite-ignore`.
        ok, message = _switch_result(root, ["checkout", "--no-overwrite-ignore", name], name)
    return ok, message


def create_branch(root, name):
    """Create and switch to a new local branch. Return (ok, message)."""
    name = (name or "").strip()
    ok, message = validate_branch_name(root, name)
    if not ok:
        return False, message
    ok, message = _switch_result(root, ["switch", "--no-overwrite-ignore", "-c", name], name)
    if not ok and (_unsupported_switch(message)
                   or _unsupported_no_overwrite_ignore(message)):
        ok, message = _switch_result(root, ["checkout", "--no-overwrite-ignore", "-b", name], name)
    return ok, message
