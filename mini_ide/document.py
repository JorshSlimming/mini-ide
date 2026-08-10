import os


class DocumentState:
    """State of one open editor document (path, dirty/conflict flags,
    disk snapshot and its autosave timer).

    The GTK layer injects the timer primitives, so this class is fully
    unit-testable without a display.
    """

    def __init__(self, path, buffer, schedule, remove, save_cb):
        self.path = path
        self.buffer = buffer
        self.dirty = False
        self.conflict = False
        self.deleted = False
        self.saved_snap = None
        self.save_timer = None
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
        """User modified the buffer: mark dirty and (re)arm autosave."""
        self.dirty = True
        self.conflict = False
        if not self.deleted:
            self.schedule_autosave(800)
        return self.save_timer is not None

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

    def mark_saved(self):
        """Record a successful save of this buffer."""
        self.dirty = False
        self.conflict = False
        self.snapshot_from_disk()

    def mark_deleted(self):
        self.deleted = True
        self.dirty = False
        self.cancel_autosave()

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
