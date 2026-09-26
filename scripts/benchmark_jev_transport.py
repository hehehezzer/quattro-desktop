#!/usr/bin/env python3
"""Opt-in live connection-reuse experiment. Not a production transport or worker."""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from quattro_agent.jev import JevClient, JevFailure, MAX_RESPONSE_BYTES, decode, serialize_state
from quattro_agent.provider_access import resolve_typesafe_credential
from benchmark_jev_live import distribution


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ExperimentalClient(JevClient):
    """Fixed-origin, verified TLS, no redirects/proxies/retries. Benchmark only."""
    def __init__(self, key):
        super().__init__(key, 3, opener=object())
        self.connection = http.client.HTTPSConnection('api.typesafe.ai', timeout=3)
        self.connect_ms = []
        self.versions = set()

    def close(self):
        self.connection.close()

    def _request(self, path, payload=None):
        if self.connection.sock is None:
            started = time.perf_counter()
            self.connection.connect()
            self.connect_ms.append((time.perf_counter() - started) * 1000)
        data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        self.connection.request('GET' if data is None else 'POST', path, body=data,
            headers={'Authorization': 'Bearer ' + self._key, 'Content-Type': 'application/json'})
        with self.connection.getresponse() as response:
            self.versions.add(response.version)
            if response.status != 200:
                raise JevFailure('http_error')
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise JevFailure('response_too_large')
        return decode(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, choices=range(10, 51), default=10)
    args = parser.parse_args()
    key = resolve_typesafe_credential()
    if not key:
        raise JevFailure('missing_credential')
    state = serialize_state('Debug the repository regression and reproduce the root cause')
    session = ExperimentalClient(key)
    rows = {name: [] for name in ('urllib_fresh', 'https_per_turn', 'https_session')}
    try:
        for index in range(args.samples):
            order = list(rows)
            order = order[index % 3:] + order[:index % 3]
            for mode in order:
                client = JevClient(key, 3, opener=urllib.request.build_opener(
                    urllib.request.ProxyHandler({}), NoRedirect(),
                )) if mode == 'urllib_fresh' else (
                    session if mode == 'https_session' else ExperimentalClient(key))
                connections_before = len(getattr(client, 'connect_ms', []))
                started = time.perf_counter()
                try:
                    result = client.evaluate(state)
                    rows[mode].append({
                        'wall_ms': (time.perf_counter() - started) * 1000,
                        'jev_rtt_ms': result['jev_latency_ms'],
                        'catalog_ms': result['catalog_latency_ms'],
                        'new_connections': len(getattr(client, 'connect_ms', [])) - connections_before
                            if mode != 'urllib_fresh' else None,
                        'connect_ms': getattr(client, 'connect_ms', [])[connections_before:],
                        'http_versions': sorted(getattr(client, 'versions', [])),
                        'model': result['response']['model'],
                    })
                finally:
                    if mode == 'https_per_turn':
                        client.close()
    finally:
        session.close()
    print(json.dumps({
        'measurement': 'LIVE transport-only; catalog verified every evaluation; no execution calls',
        'dns_tcp_tls': 'combined connect measurement; phases not separately attributed',
        'modes': {name: {
            **{metric: distribution([row[metric] for row in samples])
               for metric in ('wall_ms', 'jev_rtt_ms', 'catalog_ms')},
            'connect_ms': distribution([value for row in samples for value in row['connect_ms']]),
            'new_connections': sum(row['new_connections'] or 0 for row in samples)
                if name != 'urllib_fresh' else None,
            'http_versions': sorted({v for row in samples for v in row['http_versions']}),
            'models': sorted({row['model'] for row in samples}),
        } for name, samples in rows.items()},
    }, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'status': 'failed', 'reason': 'transport_experiment_failed'}))
        raise SystemExit(1) from None
