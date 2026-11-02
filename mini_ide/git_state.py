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


def snapshot(root):
    """Describe the current HEAD state of the repository containing *root*."""
    top = repo_root(root)
    if not top:
        return {"is_repo": False, "root": None, "branch": None,
                "head": None, "detached": False, "dirty": False}

    branch = None
    head = None
    detached = False
    result = _git(top, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    if result is not None and result.returncode == 0:
        branch = result.stdout.strip() or None
    else:
        detached = True
        result = _git(top, ["rev-parse", "--short", "HEAD"])
        if result is not None and result.returncode == 0:
            head = result.stdout.strip() or None

    dirty = False
    result = _git(top, ["status", "--porcelain", "--untracked-files=no"])
    if result is not None and result.returncode == 0:
        dirty = bool(result.stdout.strip())

    return {"is_repo": True, "root": top, "branch": branch, "head": head,
            "detached": detached, "dirty": dirty}


def label(info):
    """Short human label for a snapshot."""
    if not info or not info.get("is_repo"):
        return ""
    if info.get("detached"):
        return "detached@%s" % (info.get("head") or "HEAD")
    return info.get("branch") or "HEAD"


def branches(root):
    """List local branches, most recently committed first."""
    top = repo_root(root)
    if not top:
        return []
    result = _git(top, ["for-each-ref", "--sort=-committerdate",
                        "--format=%(refname:short)", "refs/heads"])
    if result is None or result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines()
            if line.strip()]


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


def _switch_result(root, args, name):
    result = _git(root, args, timeout=SWITCH_TIMEOUT)
    if result is None:
        return False, "Git is not available."
    if result.returncode == 0:
        return True, _output(result) or "Switched to branch “%s”." % name
    return False, _output(result) or "Could not switch to “%s”." % name


def switch_branch(root, name):
    """Switch to an existing local branch. Return (ok, message)."""
    name = (name or "").strip()
    ok, message = validate_branch_name(root, name)
    if not ok:
        return False, message
    ok, message = _switch_result(root, ["switch", "--", name], name)
    if not ok and _unsupported_switch(message):
        # Git older than 2.23 has no `switch`; checkout is the equivalent.
        ok, message = _switch_result(root, ["checkout", name], name)
    return ok, message


def create_branch(root, name):
    """Create and switch to a new local branch. Return (ok, message)."""
    name = (name or "").strip()
    ok, message = validate_branch_name(root, name)
    if not ok:
        return False, message
    ok, message = _switch_result(root, ["switch", "-c", name], name)
    if not ok and _unsupported_switch(message):
        ok, message = _switch_result(root, ["checkout", "-b", name], name)
    return ok, message
