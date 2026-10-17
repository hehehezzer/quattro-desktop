"""Native Windows source-containment and storage-privacy behavior."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@unittest.skipUnless(os.name == "nt", "Requires native Windows handle and ACL APIs")
class WindowsBoundaryTests(unittest.TestCase):
    def test_read_pins_ancestor_against_replacement_and_bounds_content(self):
        import ctypes
        from quattro_core._windows import read_file, _api
        kernel, _ = _api()
        invalid = ctypes.c_void_p(-1).value
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent = root / "nested"
            parent.mkdir()
            content = "Verified source evidence: café."
            (parent / "evidence.txt").write_text(content, encoding="utf-8")
            fstat = os.fstat
            attempted = []
            def writable_handle():
                return kernel.CreateFileW(str(parent), 0x40000000, 7, None, 3, 0x02200000, None)

            def inspect(descriptor):
                if not attempted:
                    attempted.append(True)
                    with self.assertRaises(OSError):
                        parent.rename(root / "moved")
                    handle = writable_handle()
                    error = ctypes.get_last_error()
                    if handle != invalid:
                        kernel.CloseHandle(handle)
                    self.assertEqual((handle,error),(invalid,32))
                return fstat(descriptor)

            with mock.patch("os.fstat", side_effect=inspect):
                actual, info = read_file(root, Path("nested/evidence.txt"), 1024)
            self.assertEqual(actual, content)
            self.assertEqual(info.st_size, len(content.encode("utf-8")))
            with self.assertRaises(ValueError):
                read_file(root, Path("nested/evidence.txt"), 4)
            handle = writable_handle()
            self.assertNotEqual(handle,invalid)
            kernel.CloseHandle(handle)
            parent.rename(root / "released")
            self.assertTrue((root / "released/evidence.txt").is_file())

    def test_public_acl_is_rejected_before_database_creation(self):
        from quattro_core._windows import require_private_acl, private_directory
        from quattro_core.retrieval import private_database
        for grant in ("*S-1-1-0:(OI)(CI)(R)", "*S-1-1-0:(OI)(IO)(R)"):
            with self.subTest(grant=grant), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                storage = root / "storage"
                private_directory(storage)
                require_private_acl(storage)
                subprocess.run(["icacls", str(storage), "/grant", grant],
                               check=True, capture_output=True, timeout=10)
                with self.assertRaises(ValueError):
                    private_database(storage / "denied.sqlite3")
                self.assertFalse((storage / "denied.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
