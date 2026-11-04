"""Pure helpers for keeping open documents in sync across branch switches.

Git may rewrite or remove files while the editor is open. The GTK layer
pauses autosave, records a content digest before the operation, and applies
the decisions produced here afterwards. Keeping the decision logic pure
makes the dangerous cases testable without a display.
"""
import hashlib
import os

UNCHANGED = "unchanged"
RELOAD = "reload"
CONFLICT = "conflict"
DELETED = "deleted"
REAPPEARED_RELOAD = "reappeared-reload"
REAPPEARED_CONFLICT = "reappeared-conflict"


def file_digest(path):
    """SHA-256 of a file's bytes, or ``None`` when it cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def disk_snapshot(path):
    """Return ``(mtime_ns, size)`` or ``None`` when the file is gone."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def reconcile_action(dirty, conflict, deleted, disk_exists,
                     before_digest=None, after_digest=None,
                     snapshot_changed=False):
    """Decide what to do with one document after a branch operation.

    ``before_digest`` is the digest captured before the switch when that
    was possible. When it is ``None`` (for example after an external
    ``git switch``), ``snapshot_changed`` is used as the fallback signal.
    """
    if not disk_exists:
        return DELETED
    if deleted:
        if dirty or conflict:
            return REAPPEARED_CONFLICT
        return REAPPEARED_RELOAD
    if before_digest is not None:
        changed = after_digest != before_digest
    else:
        changed = bool(snapshot_changed)
    if not changed:
        return UNCHANGED
    if dirty or conflict:
        return CONFLICT
    return RELOAD
