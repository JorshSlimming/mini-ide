import os
import tempfile


def atomic_write(path, text):
    d = os.path.dirname(path) or "."
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix=".%s." % os.path.basename(path), dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def validate_child_name(name):
    name = name.strip()
    if not name or name in {".", ".."}:
        return None
    if os.path.basename(name) != name:
        return None
    return name


def looks_binary(path, sample=8192):
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(sample)
    except OSError:
        return False


def create_new_file(path):
    with open(path, "x", encoding="utf-8"):
        pass


def create_new_dir(path):
    os.makedirs(path, exist_ok=False)


def path_inside(root, target):
    try:
        root_real = os.path.realpath(root)
        target_real = os.path.realpath(target)
        return os.path.commonpath([root_real, target_real]) == root_real
    except (OSError, ValueError):
        return False


def copy_dest_safe(src, dst):
    try:
        src_real = os.path.realpath(src)
        dst_real = os.path.realpath(dst)
        return os.path.commonpath([src_real, dst_real]) != src_real
    except (OSError, ValueError):
        return False
