import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mini_ide import file_ops


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_creates_new_file(self):
        p = os.path.join(self.dir, "a.txt")
        file_ops.atomic_write(p, "hola")
        self.assertEqual(open(p).read(), "hola")

    def test_replaces_existing_file(self):
        p = os.path.join(self.dir, "a.txt")
        file_ops.atomic_write(p, "v1")
        file_ops.atomic_write(p, "v2")
        self.assertEqual(open(p).read(), "v2")

    def test_preserves_mode(self):
        p = os.path.join(self.dir, "a.sh")
        file_ops.atomic_write(p, "#!/bin/sh\n")
        os.chmod(p, 0o755)
        file_ops.atomic_write(p, "#!/bin/sh\necho hi\n")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o755)

    def test_no_temp_files_left(self):
        p = os.path.join(self.dir, "a.txt")
        file_ops.atomic_write(p, "x")
        leftovers = [f for f in os.listdir(self.dir) if f.startswith(".a.txt.")]
        self.assertEqual(leftovers, [])

    def test_new_file_uses_private_mode(self):
        p = os.path.join(self.dir, "secret.env")
        file_ops.atomic_write(p, "TOKEN=1\n")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)

    def test_chmod_failure_does_not_create_target(self):
        p = os.path.join(self.dir, "secret.env")
        with mock.patch.object(file_ops.os, "chmod",
                               side_effect=OSError("chmod failed")):
            with self.assertRaises(OSError):
                file_ops.atomic_write(p, "TOKEN=1\n")
        self.assertFalse(os.path.exists(p))
        leftovers = [f for f in os.listdir(self.dir)
                     if f.startswith(".secret.env.")]
        self.assertEqual(leftovers, [])

    def test_failed_write_cleans_temp(self):
        p = os.path.join(self.dir, "a.txt")
        file_ops.atomic_write(p, "keep")
        with self.assertRaises(Exception):
            file_ops.atomic_write(p, None)
        leftovers = [f for f in os.listdir(self.dir) if f.startswith(".a.txt.")]
        self.assertEqual(leftovers, [])
        self.assertEqual(open(p).read(), "keep")


class AtomicCreateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_creates_new_file(self):
        p = os.path.join(self.dir, "new.txt")
        file_ops.atomic_create(p, "hola")
        self.assertEqual(open(p).read(), "hola")

    def test_new_file_is_private_even_with_permissive_umask(self):
        p = os.path.join(self.dir, "secret.env")
        file_ops.atomic_create(p, "TOKEN=1\n")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)

    def test_new_file_is_private_with_umask_077_in_subprocess(self):
        p = os.path.join(self.dir, "secret.env")
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        code = (
            "import os, sys\n"
            "sys.path.insert(0, %r)\n"
            "os.umask(0o077)\n"
            "from mini_ide import file_ops\n"
            "file_ops.atomic_create(%r, 'TOKEN=1\\n')\n"
            "print(oct(os.stat(%r).st_mode & 0o777))\n"
            % (root, p, p))
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=root, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(result.stdout.strip(), "0o600")

    def test_existing_file_is_not_overwritten(self):
        p = os.path.join(self.dir, "new.txt")
        with open(p, "w") as f:
            f.write("precious")
        with self.assertRaises(FileExistsError):
            file_ops.atomic_create(p, "replacement")
        self.assertEqual(open(p).read(), "precious")

    def test_no_temp_files_left(self):
        p = os.path.join(self.dir, "new.txt")
        file_ops.atomic_create(p, "x")
        leftovers = [f for f in os.listdir(self.dir)
                     if f.startswith(".new.txt.")]
        self.assertEqual(leftovers, [])


class AtomicWriteCheckedTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_replaces_only_matching_state(self):
        p = os.path.join(self.dir, "a.txt")
        with open(p, "w") as f:
            f.write("v1")
        expected = file_ops.file_state(p)

        file_ops.atomic_write_checked(p, "v2", expected)

        self.assertEqual(open(p).read(), "v2")

    def test_changed_target_is_preserved(self):
        p = os.path.join(self.dir, "a.txt")
        with open(p, "w") as f:
            f.write("v1")
        expected = file_ops.file_state(p)
        with open(p, "w") as f:
            f.write("newer")

        with self.assertRaises(file_ops.FileChangedError):
            file_ops.atomic_write_checked(p, "old-buffer", expected)

        self.assertEqual(open(p).read(), "newer")

    def test_missing_target_is_not_created(self):
        p = os.path.join(self.dir, "missing.txt")
        expected = (1, 2, 0o644)

        with self.assertRaises(file_ops.FileChangedError):
            file_ops.atomic_write_checked(p, "x", expected)

        self.assertFalse(os.path.exists(p))

    def test_unknown_target_state_fails_closed(self):
        p = os.path.join(self.dir, "missing.txt")

        with self.assertRaises(file_ops.FileChangedError):
            file_ops.atomic_write_checked(p, "x", None)

        self.assertFalse(os.path.exists(p))
        leftovers = [f for f in os.listdir(self.dir)
                     if f.startswith(".missing.txt.")]
        self.assertEqual(leftovers, [])

    def test_preserves_target_mode(self):
        p = os.path.join(self.dir, "secret.env")
        with open(p, "w") as f:
            f.write("old")
        os.chmod(p, 0o600)
        expected = file_ops.file_state(p)

        file_ops.atomic_write_checked(p, "new", expected)

        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)

    def test_chmod_failure_preserves_existing_target(self):
        p = os.path.join(self.dir, "secret.env")
        with open(p, "w") as f:
            f.write("old")
        os.chmod(p, 0o600)
        expected = file_ops.file_state(p)

        with mock.patch.object(file_ops.os, "chmod",
                               side_effect=OSError("chmod failed")):
            with self.assertRaises(OSError):
                file_ops.atomic_write_checked(p, "new", expected)

        self.assertEqual(open(p).read(), "old")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)


class ValidateChildNameTest(unittest.TestCase):
    def test_accepts_simple_names(self):
        self.assertEqual(file_ops.validate_child_name("foo.py"), "foo.py")
        self.assertEqual(file_ops.validate_child_name(" a.txt "), "a.txt")
        self.assertEqual(file_ops.validate_child_name("nombre con espacios.txt"), "nombre con espacios.txt")

    def test_rejects_path_escapes(self):
        for name in ("../x", "../../x", "/tmp/x", "folder/name", "a//b", "..", ".", "", "   "):
            self.assertIsNone(file_ops.validate_child_name(name), name)


class CreateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_create_new_file(self):
        p = os.path.join(self.dir, "new.py")
        file_ops.create_new_file(p)
        self.assertTrue(os.path.isfile(p))

    def test_create_existing_file_raises_without_truncating(self):
        p = os.path.join(self.dir, "new.py")
        with open(p, "w") as f:
            f.write("precious")
        with self.assertRaises(FileExistsError):
            file_ops.create_new_file(p)
        self.assertEqual(open(p).read(), "precious")

    def test_create_new_dir(self):
        p = os.path.join(self.dir, "sub")
        file_ops.create_new_dir(p)
        self.assertTrue(os.path.isdir(p))

    def test_create_existing_dir_raises(self):
        p = os.path.join(self.dir, "sub")
        os.makedirs(p)
        with self.assertRaises(FileExistsError):
            file_ops.create_new_dir(p)


class PathInsideTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.root = os.path.join(self.dir, "project")
        os.makedirs(os.path.join(self.root, "sub"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_inside_ok(self):
        self.assertTrue(file_ops.path_inside(self.root, os.path.join(self.root, "x.py")))
        self.assertTrue(file_ops.path_inside(self.root, os.path.join(self.root, "sub", "y.py")))
        self.assertTrue(file_ops.path_inside(self.root, os.path.join(self.root, "sub", "deep", "z.txt")))

    def test_outside_rejected(self):
        self.assertFalse(file_ops.path_inside(self.root, os.path.join(self.dir, "outside.txt")))
        self.assertFalse(file_ops.path_inside(self.root, os.path.join(self.root, "..", "outside.txt")))
        self.assertFalse(file_ops.path_inside(self.root, "/tmp/whatever"))

    def test_sibling_prefix_not_confused(self):
        self.assertFalse(file_ops.path_inside(self.root, self.root + "2"))

    def test_symlink_escape_rejected(self):
        target = os.path.join(self.dir, "outside.txt")
        with open(target, "w") as f:
            f.write("x")
        link = os.path.join(self.root, "link")
        os.symlink(self.dir, link)
        self.assertFalse(file_ops.path_inside(self.root, os.path.join(link, "outside.txt")))


class CopyDestSafeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_siblings_ok(self):
        src = os.path.join(self.dir, "src")
        dst = os.path.join(self.dir, "dst")
        self.assertTrue(file_ops.copy_dest_safe(src, dst))

    def test_prefix_sibling_ok(self):
        src = os.path.join(self.dir, "src")
        dst = os.path.join(self.dir, "src-copy")
        self.assertTrue(file_ops.copy_dest_safe(src, dst))

    def test_into_own_descendant_rejected(self):
        src = os.path.join(self.dir, "src")
        dst = os.path.join(self.dir, "src", "nested", "src")
        self.assertFalse(file_ops.copy_dest_safe(src, dst))

    def test_same_path_rejected(self):
        src = os.path.join(self.dir, "src")
        self.assertFalse(file_ops.copy_dest_safe(src, src))

    def test_symlink_loop_rejected(self):
        a = os.path.join(self.dir, "a")
        os.makedirs(a)
        os.symlink(a, os.path.join(a, "back"))
        self.assertFalse(file_ops.copy_dest_safe(a, os.path.join(a, "back", "a")))


class LooksBinaryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_text_is_not_binary(self):
        p = os.path.join(self.dir, "a.txt")
        with open(p, "w") as f:
            f.write("hola mundo\n")
        self.assertFalse(file_ops.looks_binary(p))

    def test_nul_bytes_are_binary(self):
        p = os.path.join(self.dir, "a.bin")
        with open(p, "wb") as f:
            f.write(b"\x01\x00\x02")
        self.assertTrue(file_ops.looks_binary(p))


if __name__ == "__main__":
    unittest.main()
