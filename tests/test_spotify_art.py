"""Bounded Spotify artwork cache behavior."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location("spotify_art", Path(__file__).parents[1] / "src/quattro_spotify_art.py")
art = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(art)


class SpotifyArtworkTests(unittest.TestCase):
    def test_only_spotify_cdn_image_ids_are_accepted(self):
        image = "a" * 40
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.assertEqual(art.cache_path(f"https://i.scdn.co/image/{image}", home).name, image + ".jpg")
            for url in [
                "https://evil.example/image/" + image,
                "http://i.scdn.co/image/" + image,
                "https://i.scdn.co/image/" + image + "?x=1",
                "https://i.scdn.co/image/../../secret",
            ]:
                self.assertIsNone(art.cache_path(url, home))

    def test_fetch_caches_jpeg_and_reuses_local_file(self):
        url = "https://i.scdn.co/image/" + "b" * 40
        response = MagicMock()
        response.__enter__.return_value.geturl.return_value = url
        response.__enter__.return_value.headers = {"Content-Type": "image/jpeg"}
        response.__enter__.return_value.read.return_value = b"\xff\xd8\xffcover"
        with tempfile.TemporaryDirectory() as temp, patch.object(art.urllib.request, "urlopen", return_value=response) as get:
            first = art.fetch(url, Path(temp))
            self.assertEqual(Path(first.removeprefix("file://")).read_bytes(), b"\xff\xd8\xffcover")
            self.assertEqual(art.fetch(url, Path(temp)), first)
            get.assert_called_once()

    def test_oversized_or_failed_image_uses_fallback(self):
        url = "https://i.scdn.co/image/" + "c" * 40
        response = MagicMock()
        response.__enter__.return_value.geturl.return_value = url
        response.__enter__.return_value.headers = {"Content-Type": "image/jpeg"}
        response.__enter__.return_value.read.return_value = b"\xff\xd8\xff" + b"x" * art.MAX_BYTES
        with tempfile.TemporaryDirectory() as temp, patch.object(art.urllib.request, "urlopen", return_value=response):
            self.assertEqual(art.fetch(url, Path(temp)), "")
            self.assertFalse(any(Path(temp).rglob("*.jpg")))


if __name__ == "__main__":
    unittest.main()
