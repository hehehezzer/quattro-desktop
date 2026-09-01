#!/usr/bin/env python3
"""Credential-free MCP bridge from Codex to OmniRoute image generation."""

from __future__ import annotations

import base64
import binascii
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


SERVER_NAME = "quattro-images"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-06-18"
OMNIROUTE_ENDPOINT = "http://localhost:20128/api/v1/images/generations"
DEFAULT_MODEL = "antigravity/gemini-3.1-flash-image"
ALLOWED_MODELS = frozenset({DEFAULT_MODEL})
ALLOWED_SIZES = frozenset({"1024x1024", "1536x1024", "1024x1536"})
MAX_PROMPT_LENGTH = 8000
MAX_REVISED_PROMPT_LENGTH = 8000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = ((MAX_IMAGE_BYTES + 2) // 3 * 4) + 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 180
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


class ImageBridgeError(RuntimeError):
    pass


def tool_spec() -> dict[str, Any]:
    return {
        "name": "generate_image",
        "description": (
            "Generate one image through the local OmniRoute image endpoint and save it "
            "under the current project's generated-images directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Concrete visual description of the requested image.",
                    "minLength": 1,
                    "maxLength": MAX_PROMPT_LENGTH,
                },
                "model": {
                    "type": "string",
                    "enum": sorted(ALLOWED_MODELS),
                    "default": DEFAULT_MODEL,
                },
                "size": {
                    "type": "string",
                    "enum": sorted(ALLOWED_SIZES),
                    "description": "Optional output aspect and size hint.",
                },
                "output_name": {
                    "type": "string",
                    "description": "Optional safe filename; an extension is added automatically.",
                    "pattern": SAFE_NAME.pattern,
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    }


def _request_json(payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        OMNIROUTE_ENDPOINT,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        detail = error.read(4096).decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
            detail = str(parsed.get("error", {}).get("message") or detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise ImageBridgeError(f"OmniRoute image request failed ({error.code}): {detail[:500]}") from error
    except (OSError, urllib.error.URLError) as error:
        raise ImageBridgeError(f"OmniRoute image endpoint is unavailable: {error}") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ImageBridgeError("OmniRoute image response exceeded the safe response limit")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ImageBridgeError("OmniRoute returned an invalid image response") from error
    if not isinstance(value, dict):
        raise ImageBridgeError("OmniRoute returned an unexpected image response")
    return value


def _decode_data_url(value: str) -> tuple[bytes, str]:
    header, separator, encoded = value.partition(",")
    if not separator or not header.startswith("data:image/") or ";base64" not in header:
        raise ImageBridgeError("OmniRoute returned an unsupported image data URL")
    mime = header[5:].split(";", 1)[0].lower()
    return _decode_base64(encoded), mime


def _decode_base64(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ImageBridgeError("OmniRoute returned invalid base64 image data") from error
    if not decoded or len(decoded) > MAX_IMAGE_BYTES:
        raise ImageBridgeError("Generated image was empty or exceeded the 10 MiB limit")
    return decoded


def _decode_image_url(url: str) -> tuple[bytes, str]:
    if url.startswith("data:"):
        return _decode_data_url(url)
    # The request explicitly asks OmniRoute for base64. Refuse remote URLs
    # instead of turning a provider-controlled response into an SSRF primitive.
    raise ImageBridgeError("OmniRoute returned a remote image URL instead of base64 data")


def _extract_image(response: dict[str, Any]) -> tuple[bytes, str, str | None]:
    rows = response.get("data")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise ImageBridgeError("OmniRoute response did not contain an image")
    row = rows[0]
    revised = row.get("revised_prompt") if isinstance(row.get("revised_prompt"), str) else None
    if revised is not None:
        revised = revised[:MAX_REVISED_PROMPT_LENGTH]
    encoded = row.get("b64_json")
    if isinstance(encoded, str) and encoded:
        return _decode_base64(encoded), "image/png", revised
    url = row.get("url")
    if isinstance(url, str) and url:
        data, mime = _decode_image_url(url)
        return data, mime, revised
    raise ImageBridgeError("OmniRoute response did not contain supported image data")


def _extension_for(data: bytes, mime: str) -> tuple[str, str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    raise ImageBridgeError("Generated bytes were not a supported PNG, JPEG, or WebP image")


def _save_image(data: bytes, mime: str, output_name: str | None) -> pathlib.Path:
    root = pathlib.Path.cwd().resolve()
    output_dir = root / "generated-images"
    if output_dir.exists() and output_dir.is_symlink():
        raise ImageBridgeError("generated-images must not be a symbolic link")
    output_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
    os.chmod(output_dir, 0o700)
    extension, _ = _extension_for(data, mime)
    if output_name:
        if not SAFE_NAME.fullmatch(output_name):
            raise ImageBridgeError("output_name contains unsupported characters")
        stem = pathlib.Path(output_name).stem
    else:
        stem = f"image-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    target = output_dir / f"{stem}{extension}"
    if target.exists() or target.is_symlink():
        raise ImageBridgeError(f"Refusing to overwrite existing image: {target.name}")
    descriptor, temporary = tempfile.mkstemp(prefix=".image-", dir=output_dir)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return target


def generate_image(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ImageBridgeError("Tool arguments must be an object")
    prompt = arguments.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ImageBridgeError("prompt is required")
    prompt = prompt.strip()
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise ImageBridgeError(f"prompt exceeds {MAX_PROMPT_LENGTH} characters")
    model = arguments.get("model", DEFAULT_MODEL)
    if model not in ALLOWED_MODELS:
        raise ImageBridgeError(f"unsupported image model: {model}")
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "response_format": "b64_json",
    }
    size = arguments.get("size")
    if size is not None:
        if size not in ALLOWED_SIZES:
            raise ImageBridgeError(f"unsupported image size: {size}")
        payload["size"] = size
    response = _request_json(payload)
    data, mime, revised = _extract_image(response)
    extension, mime = _extension_for(data, mime)
    del extension
    output_name = arguments.get("output_name")
    if output_name is not None and not isinstance(output_name, str):
        raise ImageBridgeError("output_name must be a string")
    path = _save_image(data, mime, output_name)
    summary = f"Generated image saved to {path}"
    if revised:
        summary += f"\nRevised prompt: {revised}"
    return {
        "content": [
            {"type": "text", "text": summary},
            {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime},
        ],
        "structuredContent": {"path": str(path), "model": model, "mimeType": mime},
    }


def _response(request_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> None:
    value: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is None:
        value["result"] = result
    else:
        value["error"] = error
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle_message(message: Any) -> None:
    if not isinstance(message, dict):
        return
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return
    if method == "initialize":
        requested = message.get("params", {}).get("protocolVersion")
        protocol = requested if requested == PROTOCOL_VERSION else PROTOCOL_VERSION
        _response(request_id, {
            "protocolVersion": protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    elif method == "ping":
        _response(request_id, {})
    elif method == "tools/list":
        _response(request_id, {"tools": [tool_spec()]})
    elif method == "tools/call":
        params = message.get("params")
        try:
            if not isinstance(params, dict) or params.get("name") != "generate_image":
                raise ImageBridgeError("unknown tool")
            _response(request_id, generate_image(params.get("arguments", {})))
        except ImageBridgeError as error:
            _response(request_id, {
                "content": [{"type": "text", "text": str(error)}],
                "isError": True,
            })
    else:
        _response(request_id, error={"code": -32601, "message": f"Method not found: {method}"})


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            handle_message(json.loads(line))
        except json.JSONDecodeError:
            _response(None, error={"code": -32700, "message": "Parse error"})
        except Exception as error:  # Fail one request safely without terminating the server.
            _response(None, error={"code": -32603, "message": f"Internal error: {error}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
