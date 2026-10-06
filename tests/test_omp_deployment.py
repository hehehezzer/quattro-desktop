from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent.omp_deployment import review_omp_runtime, verify_omp_runtime


@unittest.skipUnless(os.name == "posix", "closed OMP SDK verification requires Unix")
class OMPDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bun = self.root / "bun"
        self.bun.write_bytes(b"reviewed interpreter")
        self.closure = self.root / "sdk"
        self.package = self.closure / "node_modules" / "@oh-my-pi" / "pi-coding-agent"
        self.package.mkdir(parents=True)
        (self.package / "package.json").write_text(json.dumps({
            "name": "@oh-my-pi/pi-coding-agent", "version": "18.6.3"}))
        self.code = self.package / "index.ts"
        self.code.write_text("reviewed native source")
        self.manifest = self.root / "manifest.json"
        self.pin()

    def pin(self):
        data = review_omp_runtime(self.bun, self.package, self.closure)
        self.manifest.write_text(json.dumps(data, sort_keys=True))
        self.digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def verify(self, **overrides):
        verify_omp_runtime(self.manifest, self.bun, self.package,
                           expected_digest=overrides.get("expected_digest", self.digest))

    def test_entire_reviewed_closure_and_interpreter_match(self):
        self.verify()
        self.bun.write_bytes(b"replacement interpreter")
        with self.assertRaises(ValueError):
            self.verify()

    def test_dependency_change_extra_file_and_missing_file_are_rejected(self):
        self.code.write_text("changed dependency")
        with self.assertRaises(ValueError):
            self.verify()
        self.code.write_text("reviewed native source")
        extra = self.closure / "foreign.js"
        extra.write_text("foreign import")
        with self.assertRaises(ValueError):
            self.verify()
        extra.unlink()
        self.code.unlink()
        with self.assertRaises(ValueError):
            self.verify()

    def test_manifest_cannot_authorize_its_own_mutation(self):
        self.code.write_text("changed dependency")
        original = self.digest
        self.pin()
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            self.verify(expected_digest=original)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_external_links_and_directory_links_are_rejected(self):
        foreign = self.root / "foreign.js"
        foreign.write_text("foreign")
        link = self.closure / "escape.js"
        try:
            link.symlink_to(foreign)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(ValueError):
            self.pin()
        link.unlink()
        link.symlink_to(self.package, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.pin()

    @unittest.skipUnless(hasattr(os, "link"), "hardlinks unavailable")
    def test_hardlinked_dependency_cannot_escape_reviewed_inventory(self):
        os.link(self.code, self.root / "shared-cache-entry")
        with self.assertRaises(ValueError):
            self.verify()

    def test_invalid_manifest_shapes_and_foreign_package_rejected(self):
        self.manifest.write_text('{"version":1,"bun":[],"packageRoot":"x","closureRoot":"x","files":{},"symlinks":{}}')
        self.digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            self.verify()
        (self.package / "package.json").write_text('{"name":"foreign","version":"18.6.3"}')
        self.pin()
        with self.assertRaisesRegex(ValueError, "official OMP"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
