import os
import shutil

WARN_LARGE = 5 * 1024 * 1024
MAX_LARGE = 25 * 1024 * 1024
MAX_PDF_PIXELS = 30_000_000


def migrate_legacy_config(old_dir, new_dir):
    """Copy Mini-IDE state into PanelIDE once, retaining the original files."""
    migrated = []
    for filename in ("session.json", "recent.json"):
        old_path = os.path.join(old_dir, filename)
        new_path = os.path.join(new_dir, filename)
        if not os.path.isfile(old_path) or os.path.exists(new_path):
            continue
        try:
            os.makedirs(new_dir, exist_ok=True)
            shutil.copy2(old_path, new_path)
        except OSError:
            continue
        migrated.append(filename)
    return migrated
