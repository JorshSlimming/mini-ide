import os

from .file_ops import path_inside


class DocumentState:
    """State of one open editor document (path, dirty/conflict flags,
    disk snapshot and its autosave timer).

    The GTK layer injects the timer primitives, so this class is fully
    unit-testable without a display.
    """

    def __init__(self, path, buffer, schedule, remove, save_cb, strict_utf8=True):
        self.path = path
        self.buffer = buffer
        self.dirty = False
        self.conflict = False
        self.deleted = False
        self.unsafe = False
        self.unsafe_reason = ""
        self.saved_snap = None
        self.save_timer = None
        self.strict_utf8 = strict_utf8
        self._schedule = schedule
        self._remove = remove
        self._save_cb = save_cb

    def snapshot_from_disk(self):
        try:
            st = os.stat(self.path)
            self.saved_snap = (st.st_mtime_ns, st.st_size)
        except OSError:
            self.saved_snap = None
        return self.saved_snap

    def mark_edited(self):
        """User modified the buffer.

        A conflict is NEVER resolved implicitly by typing, and autosave
        stays suspended while the document is conflicted or deleted.
        Returns True when autosave was armed.
        """
        self.dirty = True
        if self.conflict or self.deleted:
            return False
        self.schedule_autosave(800)
        return True

    def schedule_autosave(self, delay_ms):
        if self.save_timer is not None:
            self._remove(self.save_timer)
        self.save_timer = self._schedule(delay_ms, self._on_autosave)

    def _on_autosave(self):
        self.save_timer = None
        self._save_cb(self.buffer)
        return False

    def cancel_autosave(self):
        if self.save_timer is not None:
            self._remove(self.save_timer)
            self.save_timer = None

    def resume_autosave(self):
        """Re-arm autosave after an external operation paused it.

        Returns True only when the document is still safe to autosave.
        """
        if (self.dirty and not self.conflict and not self.deleted
                and not self.unsafe):
            self.schedule_autosave(800)
            return True
        return False

    def mark_conflict(self):
        """Record an external change that must not be resolved implicitly."""
        self.conflict = True
        self.unsafe = False
        self.unsafe_reason = ""
        self.cancel_autosave()

    def mark_unsafe(self, reason):
        """Pause autosave because the disk state could not be verified.

        The buffer is deliberately preserved and never written implicitly.
        Only an explicit reload or keep-local decision clears this state.
        """
        self.mark_conflict()
        self.unsafe = True
        self.unsafe_reason = reason or "the disk state could not be verified"

    def clear_unsafe(self):
        """Forget a verification failure after an explicit decision."""
        self.unsafe = False
        self.unsafe_reason = ""

    def mark_saved(self):
        """Record a successful save of this buffer."""
        self.dirty = False
        self.conflict = False
        self.clear_unsafe()
        self.cancel_autosave()
        self.snapshot_from_disk()

    def resolve_reload(self):
        """Explicit resolution: content was reloaded from disk."""
        self.dirty = False
        self.conflict = False
        self.deleted = False
        self.clear_unsafe()
        self.cancel_autosave()
        self.snapshot_from_disk()

    def resolve_keep_local(self):
        """Explicit resolution: the user keeps the editor version.

        The current disk snapshot is acknowledged so queued monitor events
        from the same external write do not reopen the conflict dialog.
        Autosave still runs and replaces that content with the buffer.
        """
        self.conflict = False
        self.clear_unsafe()
        self.snapshot_from_disk()
        if self.dirty and not self.deleted:
            self.schedule_autosave(800)

    def external_delete(self):
        """The file disappeared externally. Dirty state is preserved so
        DELETED_DIRTY content can be recovered."""
        self.deleted = True
        self.cancel_autosave()

    def recreate(self):
        """Recovery: buffer was written back to the original path."""
        self.deleted = False
        self.mark_saved()

    def save_as(self, new_path):
        """Recovery: buffer was saved to a different path."""
        self.path = new_path
        self.deleted = False
        self.mark_saved()

    def on_disk_event(self, disk):
        """Classify a filesystem event for this open document.

        disk: (mtime_ns, size) of the current file on disk, or None when
        the file no longer exists (or could not be stat'ed).
        Returns one of: 'own', 'reload', 'conflict', 'deleted', 'ignore'.
        """
        if self.deleted:
            return 'ignore'
        if disk is None:
            return 'deleted'
        if self.saved_snap == disk:
            return 'own'
        if not self.dirty:
            return 'reload'
        return 'conflict'


def docs_under(docs, folder):
    """Documents whose path is `folder` or lives inside it."""
    return [d for d in docs
            if d.path == folder or path_inside(folder, d.path)]


def doc_relocator(docs, old_dir, new_dir):
    """Compute the new path of every open document under old_dir after a
    rename. Returns {doc: new_path}."""
    out = {}
    for doc in docs:
        p = doc.path
        if p == old_dir or path_inside(old_dir, p):
            rel = os.path.relpath(p, old_dir)
            out[doc] = new_dir if rel == "." else os.path.join(new_dir, rel)
    return out
