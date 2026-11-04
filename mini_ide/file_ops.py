import os
import tempfile


def atomic_write(path, text):
    d = os.path.dirname(path) or "."
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        # New files stay private (0600). mkstemp already creates 0600;
        # never widen a freshly created file by ignoring the process umask.
        mode = 0o600
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


class FileChangedError(OSError):
    """The target changed after its state was inspected."""


def file_state(path):
    """Return ``(mtime_ns, size, mode)`` or None when the path is absent."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_mode & 0o777)


def _write_temp(path, text, mode=None):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".%s." % os.path.basename(path), dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return tmp


def atomic_create(path, text):
    """Create *path* atomically, failing if it already exists.

    A hard link from the temporary file gives exclusive creation without a
    truncate-then-write window: concurrent creators either win or get
    FileExistsError, and an existing file is never overwritten. The new
    inode keeps mkstemp's private 0600 mode; no chmod/umask is applied.
    """
    tmp = _write_temp(path, text)
    try:
        os.link(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def atomic_write_checked(path, text, expected):
    """Atomically replace *path* only while it still matches *expected*.

    ``expected`` is the tuple returned by :func:`file_state` at the moment
    the overwrite was confirmed. It must describe an existing target: a
    missing/unknown state fails closed instead of creating a file with an
    implicit mode. The state is checked again immediately before
    ``os.replace``; the remaining verify-to-replace window is tiny but not
    zero, so callers must treat a mismatch as an aborted save.
    """
    if expected is None:
        raise FileChangedError("no existing target state to overwrite")
    if file_state(path) != expected:
        raise FileChangedError("file changed before the write")
    mode = expected[2]
    tmp = _write_temp(path, text, mode)
    try:
        if file_state(path) != expected:
            raise FileChangedError("file changed during the write")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


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
