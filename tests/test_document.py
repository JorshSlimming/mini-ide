import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mini_ide.document import DocumentState


class FakeTimer:
    def __init__(self):
        self.timers = {}
        self.next_id = 1

    def timeout_add(self, delay_ms, cb):
        tid = self.next_id
        self.next_id += 1
        self.timers[tid] = cb
        return tid

    def source_remove(self, tid):
        self.timers.pop(tid, None)

    def fire(self, tid):
        cb = self.timers.pop(tid, None)
        if cb:
            cb()


class DocumentStateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "doc.py")
        with open(self.path, "w") as f:
            f.write("v1\n")
        self.timer = FakeTimer()
        self.saves = []
        self.buffer = object()
        self.doc = DocumentState(self.path, self.buffer,
                                 self.timer.timeout_add, self.timer.source_remove,
                                 self._save_cb)

    def _save_cb(self, buf):
        self.saves.append(buf)

    def tearDown(self):
        for root, _, files in os.walk(self.dir, topdown=False):
            for f in files:
                os.unlink(os.path.join(root, f))
            os.rmdir(root)

    def snap(self):
        st = os.stat(self.path)
        return (st.st_mtime_ns, st.st_size)

    def test_snapshot_from_disk(self):
        self.assertEqual(self.doc.snapshot_from_disk(), self.snap())

    def test_edit_arms_one_autosave_timer(self):
        self.doc.snapshot_from_disk()
        self.doc.mark_edited()
        self.assertEqual(len(self.timer.timers), 1)
        self.assertIsNotNone(self.doc.save_timer)

    def test_second_edit_replaces_timer(self):
        self.doc.snapshot_from_disk()
        self.doc.mark_edited()
        first = self.doc.save_timer
        self.doc.mark_edited()
        self.assertEqual(len(self.timer.timers), 1)
        self.assertNotEqual(self.doc.save_timer, first)
        self.assertNotIn(first, self.timer.timers)

    def test_two_docs_have_independent_timers(self):
        p2 = os.path.join(self.dir, "other.py")
        with open(p2, "w") as f:
            f.write("x\n")
        doc2 = DocumentState(p2, object(), self.timer.timeout_add,
                             self.timer.source_remove, self._save_cb)
        doc2.snapshot_from_disk()
        self.doc.snapshot_from_disk()
        self.doc.mark_edited()
        doc2.mark_edited()
        self.assertEqual(len(self.timer.timers), 2)
        doc2.cancel_autosave()
        self.assertEqual(len(self.timer.timers), 1)
        self.assertIsNotNone(self.doc.save_timer)

    def test_cancel_autosave_removes_timer(self):
        self.doc.snapshot_from_disk()
        self.doc.mark_edited()
        tid = self.doc.save_timer
        self.doc.cancel_autosave()
        self.assertIsNone(self.doc.save_timer)
        self.assertNotIn(tid, self.timer.timers)

    def test_timer_fires_save_cb_with_buffer(self):
        self.doc.snapshot_from_disk()
        self.doc.mark_edited()
        tid = self.doc.save_timer
        self.timer.fire(tid)
        self.assertEqual(self.saves, [self.buffer])
        self.assertIsNone(self.doc.save_timer)

    def test_mark_saved_clears_state_and_refreshes_snapshot(self):
        self.doc.snapshot_from_disk()
        self.doc.mark_edited()
        with open(self.path, "w") as f:
            f.write("v2 external\n")
        self.doc.mark_saved()
        self.assertFalse(self.doc.dirty)
        self.assertFalse(self.doc.conflict)
        self.assertEqual(self.doc.saved_snap, self.snap())

    # --- disk event classification (AUD-002) ---

    def test_own_save_ignored(self):
        self.doc.snapshot_from_disk()
        with open(self.path, "w") as f:
            f.write("saved by us\n")
        self.doc.mark_saved()
        self.assertEqual(self.doc.on_disk_event(self.snap()), 'own')

    def test_own_save_after_atomic_replace_ignored(self):
        self.doc.snapshot_from_disk()
        self.assertEqual(self.doc.on_disk_event(self.snap()), 'own')

    def test_external_change_on_clean_doc_reloads(self):
        self.doc.snapshot_from_disk()
        self.assertFalse(self.doc.dirty)
        with open(self.path, "w") as f:
            f.write("external bigger change\n")
        self.assertEqual(self.doc.on_disk_event(self.snap()), 'reload')

    def test_external_change_on_dirty_doc_conflicts(self):
        self.doc.snapshot_from_disk()
        self.doc.mark_edited()
        with open(self.path, "w") as f:
            f.write("external bigger change\n")
        self.assertEqual(self.doc.on_disk_event(self.snap()), 'conflict')

    def test_file_gone_is_deleted(self):
        self.doc.snapshot_from_disk()
        os.unlink(self.path)
        self.assertEqual(self.doc.on_disk_event(None), 'deleted')

    def test_deleted_doc_ignores_further_events(self):
        self.doc.snapshot_from_disk()
        self.doc.mark_deleted()
        self.assertEqual(self.doc.on_disk_event(self.snap()), 'ignore')
        self.assertEqual(self.doc.on_disk_event(None), 'ignore')

    def test_mark_deleted_cancels_autosave(self):
        self.doc.snapshot_from_disk()
        self.doc.mark_edited()
        self.doc.mark_deleted()
        self.assertTrue(self.doc.deleted)
        self.assertFalse(self.doc.dirty)
        self.assertIsNone(self.doc.save_timer)
        self.assertEqual(self.timer.timers, {})

    def test_edit_after_delete_never_saves(self):
        self.doc.snapshot_from_disk()
        self.doc.mark_edited()
        self.doc.mark_deleted()
        self.doc.mark_edited()
        self.assertEqual(self.timer.timers, {})


if __name__ == "__main__":
    unittest.main()
