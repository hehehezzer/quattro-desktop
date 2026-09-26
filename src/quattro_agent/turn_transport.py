"""Private native-session HTTP adapter. Quattro retains target authority."""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading

from .omniroute import validate_omniroute_runtime_capabilities
from .turn_gate import MAX_BODY
from .privacy import redact_secret_text


class TurnTransport:
    def __init__(self, gate):
        self.gate = gate
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.cancelled = set()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_args):
                pass

            def reply(self, status, payload):
                data = json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True

            def do_POST(self):
                self.connection.settimeout(10)
                if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + owner.token):
                    self.close_connection = True
                    self.reply(403, {'error': 'session authorization required'})
                    return
                turn = None
                streaming = False
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= MAX_BODY:
                        raise ValueError('invalid request size')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError('invalid body')
                    if self.path == '/turn':
                        if body.get('frontend') != 'pi':
                            raise ValueError('invalid frontend')
                        thread_id = body.get('session_id')
                        if not isinstance(thread_id, str) or not 0 < len(thread_id) < 200:
                            raise ValueError('invalid session')
                        request_id = body.get('request_id')
                        if not isinstance(request_id, str) or not 0 < len(request_id) < 100:
                            raise ValueError('invalid request identity')
                        with owner.lock:
                            if (thread_id, request_id) in owner.cancelled:
                                raise ValueError('request cancelled before dispatch')
                            turn = owner.gate.begin(thread_id, body.get('prompt'), 'pi',
                                                    params={'request_id': request_id})
                            owner.gate.import_history(thread_id, body.get('history', []))
                        if turn.decision == 'DIRECT':
                            answer = owner.gate.direct(turn)
                        else:
                            if owner.gate.delegate is None:
                                raise RuntimeError('delegate unavailable')
                            answer = owner.gate.delegate(turn)
                            if redact_secret_text(answer)[1]:
                                turn.sensitive = True
                            if not turn.sensitive:
                                owner.gate.remember(thread_id, turn.prompt, answer)
                        self.reply(200, {'decision': turn.decision, 'response': answer,
                                         'sensitive': turn.sensitive})
                        owner.gate.finish(turn, agent_lifecycle=turn.decision == 'DELEGATE')
                    elif self.path == '/cancel':
                        with owner.lock:
                            identity = (str(body.get('session_id', '')), str(body.get('request_id', '')))
                            if len(owner.cancelled) >= 1024:
                                raise ValueError('session cancellation limit reached; restart session')
                            owner.cancelled.add(identity)
                            owner.gate.cancel_thread(identity[0], identity[1])
                        self.reply(200, {'cancelled': True})
                    elif self.path == '/responses':
                        # Codex carries this metadata per turn, including native retries.
                        meta = self.headers.get('x-codex-turn-metadata')
                        if not meta:
                            meta = (body.get('client_metadata') or {}).get('x-codex-turn-metadata')
                        metadata = json.loads(meta) if isinstance(meta, str) else {}
                        turn = owner.gate.by_plan(str(metadata.get('quattro_plan_id', '')))
                        if turn.frontend != 'codex' or turn.decision != 'DELEGATE':
                            raise ValueError('transport requires active delegated plan')
                        validate_omniroute_runtime_capabilities(timeout_seconds=3)
                        request = owner.gate.locked_body(turn, body)
                        conn, response = owner.gate._request(turn, 'POST', '/responses', request)
                        # Native tools must not act on output until the locked receipt
                        # proves fidelity. Keep this buffer strictly bounded.
                        chunks = []
                        size = 0
                        try:
                            while True:
                                owner.gate.remaining(turn)
                                chunk = response.read1(65536)
                                if not chunk:
                                    break
                                size += len(chunk)
                                if size > MAX_BODY:
                                    raise RuntimeError('delegated response exceeds transport limit')
                                chunks.append(chunk)
                        finally:
                            conn.close()
                            turn.connection = None
                        owner.gate.verify_receipt(turn)
                        payload = b''.join(chunks)
                        self.send_response(200)
                        self.send_header('Content-Type', response.getheader('Content-Type', 'text/event-stream'))
                        self.send_header('Content-Length', str(len(payload)))
                        self.end_headers()
                        streaming = True
                        self.wfile.write(payload)
                        self.wfile.flush()
                    else:
                        self.reply(404, {'error': 'unsupported session endpoint'})
                except Exception:
                    # Request/provider exception strings can contain secrets.
                    if turn and self.path == '/turn':
                        owner.gate.finish(turn, status='failed', agent_lifecycle=turn.decision == 'DELEGATE')
                    if not streaming:
                        self.reply(502, {'error': 'Quattro turn failed or exceeded its budget'})
                    self.close_connection = True

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.gate.cancel_all()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
