import json
import os
import tempfile
import unittest

from mini_ide.settings import migrate_legacy_config


class ConfigMigrationTest(unittest.TestCase):
    def test_copies_missing_state_and_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as root:
            old_dir = os.path.join(root, "mini-ide")
            new_dir = os.path.join(root, "panelide")
            os.makedirs(old_dir)
            os.makedirs(new_dir)
            old_session = {"projects": [{"root": "/old/project"}]}
            old_recents = ["/old/project"]
            with open(os.path.join(old_dir, "session.json"), "w") as file:
                json.dump(old_session, file)
            with open(os.path.join(old_dir, "recent.json"), "w") as file:
                json.dump(old_recents, file)
            new_session = {"projects": [{"root": "/new/project"}]}
            with open(os.path.join(new_dir, "session.json"), "w") as file:
                json.dump(new_session, file)

            migrated = migrate_legacy_config(old_dir, new_dir)

            self.assertEqual(migrated, ["recent.json"])
            with open(os.path.join(new_dir, "session.json")) as file:
                self.assertEqual(json.load(file), new_session)
            with open(os.path.join(new_dir, "recent.json")) as file:
                self.assertEqual(json.load(file), old_recents)
            with open(os.path.join(old_dir, "session.json")) as file:
                self.assertEqual(json.load(file), old_session)
            with open(os.path.join(old_dir, "recent.json")) as file:
                self.assertEqual(json.load(file), old_recents)
