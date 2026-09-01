from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock


SRC = pathlib.Path(__file__).parents[1] / "src"
LOADER = importlib.machinery.SourceFileLoader("quattro_menu", str(SRC / "quattro-menu"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
menu = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(menu)


class MenuTests(unittest.TestCase):
    def test_curated_packages_are_single_official_package_names(self):
        self.assertEqual(len(menu.PACKAGE_TARGETS), 7)
        for package in menu.PACKAGE_TARGETS.values():
            self.assertIsNotNone(menu.PACKAGE_NAME.fullmatch(package))

    def test_custom_package_rejects_option_and_shell_syntax(self):
        for unsafe in ("--sync", "gimp;reboot", "two packages", "$(command)"):
            with mock.patch("builtins.input", return_value=unsafe):
                self.assertIsNone(menu.resolve_package("custom"))

    def test_custom_package_accepts_arch_name_characters(self):
        with mock.patch("builtins.input", return_value="libreoffice-fresh"):
            self.assertEqual(menu.resolve_package("custom"), "libreoffice-fresh")

    def test_unknown_curated_package_is_rejected(self):
        self.assertIsNone(menu.resolve_package("unknown"))

    def test_json_validation_reports_valid_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "ai.json"
            path.write_text(json.dumps({"schemaVersion": 1}), encoding="utf-8")
            self.assertEqual(menu.validate_json(path), (True, ""))
            path.write_text("{", encoding="utf-8")
            valid, message = menu.validate_json(path)
            self.assertFalse(valid)
            self.assertTrue(message)

    def test_install_command_uses_argument_vector(self):
        found = mock.Mock(returncode=0)
        absent = mock.Mock(returncode=1)
        installed = mock.Mock(returncode=0)
        with (
            mock.patch.object(menu, "resolve_package", return_value="gimp"),
            mock.patch.object(menu, "require", side_effect=lambda command: f"/usr/bin/{command}"),
            mock.patch.object(menu, "run", side_effect=[found, absent, installed]) as run,
            mock.patch("builtins.input", return_value="yes"),
        ):
            self.assertEqual(menu.install_package("gimp"), 0)
        self.assertEqual(
            run.call_args_list[-1].args[0],
            ["/usr/bin/sudo", "/usr/bin/pacman", "-S", "--needed", "gimp"],
        )

    def test_search_indexes_files_directories_and_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            pictures = root / "Holiday Photos"
            pictures.mkdir()
            image = pictures / "sunset.png"
            image.write_bytes(b"image")
            document = root / "sunset-notes.txt"
            document.write_text("notes", encoding="utf-8")

            entries = menu.build_search_index([root])
            results = menu.search_files("sunset", entries)

        self.assertEqual([result["name"] for result in results], ["sunset.png", "sunset-notes.txt"])
        self.assertEqual(results[0]["kind"], "Image")
        directory_result = menu.search_files("holiday", entries)
        self.assertEqual(directory_result[0]["kind"], "Directory")

    def test_search_prunes_generated_dependency_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "node_modules" / "package").mkdir(parents=True)
            (root / "node_modules" / "package" / "hidden.js").write_text("", encoding="utf-8")
            (root / "visible.js").write_text("", encoding="utf-8")

            entries = menu.build_search_index([root])

        paths = [path for path, _ in entries]
        self.assertTrue(any(path.endswith("visible.js") for path in paths))
        self.assertFalse(any("node_modules" in path for path in paths))

    def test_search_prunes_authentication_material(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / ".ssh").mkdir()
            (root / ".ssh" / "id_ed25519").write_text("private", encoding="utf-8")
            (root / "quattro-ai" / "codex").mkdir(parents=True)
            (root / "quattro-ai" / "codex" / "auth.json").write_text("{}", encoding="utf-8")
            (root / "auth.json").write_text("{}", encoding="utf-8")
            (root / "photo.png").write_bytes(b"image")

            entries = menu.build_search_index([root])

        paths = [path for path, _ in entries]
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("photo.png"))

    def test_search_cache_is_private_and_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "report.pdf").write_text("", encoding="utf-8")
            cache = root / "cache" / "index.json"

            first = menu.load_search_index([root], cache, max_age=60)
            second = menu.load_search_index([], cache, max_age=60)

            self.assertEqual(first, second)
            self.assertEqual(cache.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
