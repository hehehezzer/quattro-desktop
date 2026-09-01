from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

import sys

SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
import quattro_image_mcp as bridge


PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


class Response:
    def __init__(self, value: dict):
        self.data = json.dumps(value).encode()
        self.headers = mock.Mock()
        self.headers.get_content_type.return_value = "application/json"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int):
        return self.data[:limit]


class ImageBridgeTests(unittest.TestCase):
    def test_tool_schema_has_bounded_allowlists(self):
        schema = bridge.tool_spec()["inputSchema"]
        self.assertEqual(schema["properties"]["model"]["enum"], [bridge.DEFAULT_MODEL])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["prompt"]["maxLength"], bridge.MAX_PROMPT_LENGTH)

    def test_generate_saves_private_image_and_returns_mcp_image(self):
        payload = {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch.object(bridge.urllib.request, "urlopen", return_value=Response(payload)), \
             mock.patch.object(pathlib.Path, "cwd", return_value=pathlib.Path(temporary)):
            result = bridge.generate_image({"prompt": "A small blue square", "output_name": "smoke"})
            path = pathlib.Path(result["structuredContent"]["path"])
            self.assertEqual(path.read_bytes(), PNG)
            self.assertEqual(path.name, "smoke.png")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(result["content"][1]["type"], "image")

    def test_rejects_unknown_model_before_network(self):
        with self.assertRaisesRegex(bridge.ImageBridgeError, "unsupported image model"):
            bridge.generate_image({"prompt": "test", "model": "unknown/image"})

    def test_rejects_remote_image_url(self):
        with self.assertRaisesRegex(bridge.ImageBridgeError, "remote image URL"):
            bridge._extract_image({"data": [{"url": "https://example.com/image.png"}]})

    def test_rejects_non_image_bytes_even_with_image_mime(self):
        with self.assertRaisesRegex(bridge.ImageBridgeError, "supported PNG"):
            bridge._extension_for(b"not-an-image", "image/png")

    def test_rejects_symlink_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            target = root / "elsewhere"
            target.mkdir()
            (root / "generated-images").symlink_to(target, target_is_directory=True)
            with mock.patch.object(pathlib.Path, "cwd", return_value=root):
                with self.assertRaisesRegex(bridge.ImageBridgeError, "symbolic link"):
                    bridge._save_image(PNG, "image/png", "safe")

    def test_initialize_and_tools_list_protocol(self):
        output = io.StringIO()
        with mock.patch.object(bridge.sys, "stdout", output):
            bridge.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
            bridge.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]["result"]["serverInfo"]["name"], bridge.SERVER_NAME)
        self.assertEqual(rows[1]["result"]["tools"][0]["name"], "generate_image")

    def test_unsupported_protocol_falls_back_to_supported_version(self):
        output = io.StringIO()
        with mock.patch.object(bridge.sys, "stdout", output):
            bridge.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2099-01-01"}})
        row = json.loads(output.getvalue())
        self.assertEqual(row["result"]["protocolVersion"], bridge.PROTOCOL_VERSION)

    def test_revised_prompt_is_bounded(self):
        encoded = base64.b64encode(PNG).decode()
        _data, _mime, revised = bridge._extract_image({
            "data": [{"b64_json": encoded, "revised_prompt": "x" * 20000}],
        })
        self.assertEqual(len(revised), bridge.MAX_REVISED_PROMPT_LENGTH)


if __name__ == "__main__":
    unittest.main()
