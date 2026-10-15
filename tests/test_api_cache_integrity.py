"""HTTP regressions for manifest freshness, failures, and cache publication.

Exercise serve_api's actual handler on an ephemeral loopback port. Only the
server's blocking entry point is captured; requests, parsing, and caching are
real. Query URIs may share validators, but each URI must revalidate correctly.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from http.server import ThreadingHTTPServer
import json
import os
import sys
import threading
from types import SimpleNamespace

import pytest

from aigit import core


_TIMEOUT = 5
_ROWS = [
    {'path': 'src/a.py', 'anchor': 'alpha'},
    {'path': 'src/b.py', 'anchor': 'bravo'},
    {'path': 'docs/readme.md', 'anchor': 'intro'},
]


def _write_manifest(path, rows):
    path.write_bytes(
        b''.join((json.dumps(row, sort_keys=True) + '\n').encode('utf-8') for row in rows)
    )


@dataclass(frozen=True)
class _Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        assert self.headers.get('content-type', '').startswith('application/json')
        assert int(self.headers['content-length']) == len(self.body)
        return json.loads(self.body)


class _API:
    def __init__(self, manifest, server):
        self.manifest = manifest
        self.server = server

    def get(self, target='/chunks', etag=None):
        connection = HTTPConnection(*self.server.server_address, timeout=_TIMEOUT)
        try:
            headers = {} if etag is None else {'If-None-Match': etag}
            connection.request('GET', target, headers=headers)
            response = connection.getresponse()
            return _Response(
                response.status,
                {key.lower(): value for key, value in response.getheaders()},
                response.read(),
            )
        except (HTTPException, OSError) as exc:
            pytest.fail(
                f'GET {target} dropped/failed before a complete HTTP response: '
                f'{type(exc).__name__}: {exc}; '
                f'handler errors: {self.server.handler_errors!r}'
            )
        finally:
            connection.close()


@pytest.fixture
def api(tmp_path, monkeypatch):
    semantic_dir = tmp_path / '.semantic'
    semantic_dir.mkdir()
    manifest = semantic_dir / 'manifest.jsonl'
    _write_manifest(manifest, _ROWS)
    captured = []

    class CapturingServer(ThreadingHTTPServer):
        # Join request workers at close; bound their socket reads as well.
        daemon_threads = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.handler_errors = []
            captured.append(self)

        def serve_forever(self, poll_interval=0.01):
            # Let serve_api construct its real closure/handler synchronously.
            pass

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(_TIMEOUT)
            return connection, address

        def handle_error(self, request, client_address):
            self.handler_errors.append(repr(sys.exc_info()[1]))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(core, 'ThreadingHTTPServer', CapturingServer)
    core.serve_api(argparse.Namespace(host='127.0.0.1', port=0))
    assert len(captured) == 1
    server = captured[0]
    thread = threading.Thread(
        target=ThreadingHTTPServer.serve_forever,
        args=(server,),
        kwargs={'poll_interval': 0.01},
        daemon=True,
        name='test-api-cache-integrity',
    )
    thread.start()
    client = _API(manifest, server)
    try:
        health = client.get('/healthz')
        assert health.status == 200
        assert health.json() == {'status': 'ok'}
        yield client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=_TIMEOUT)
        assert not thread.is_alive(), 'HTTP server did not shut down'


@pytest.mark.parametrize(
    ('target', 'expected'),
    [
        ('/chunks', {'chunks': _ROWS, 'total': 3, 'offset': 0, 'limit': None}),
        (
            '/chunks?path=src/&offset=1&limit=1',
            {'chunks': _ROWS[1:2], 'total': 2, 'offset': 1, 'limit': 1},
        ),
        (
            '/chunks?path=docs/',
            {'chunks': _ROWS[2:], 'total': 1, 'offset': 0, 'limit': None},
        ),
        ('/chunks?limit=0', {'chunks': [], 'total': 3, 'offset': 0, 'limit': 0}),
    ],
    ids=['full', 'filtered-page', 'filtered', 'empty-page'],
)
def test_unchanged_representation_revalidates_at_its_own_uri(api, target, expected):
    first = api.get(target)
    assert first.status == 200
    assert first.json() == expected
    assert first.headers['cache-control'] == 'no-cache'
    etag = first.headers['etag']

    cached = api.get(target, etag)
    assert cached.status == 304
    assert cached.headers['etag'] == etag
    assert cached.body == b''
    repeated = api.get(target)
    assert repeated.body == first.body
    assert repeated.headers['etag'] == etag


def _replace_preserving_signature(api):
    previous = api.manifest.stat()
    updated = [dict(row, anchor='omega') for row in _ROWS]
    _write_manifest(api.manifest, updated)
    os.utime(api.manifest, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    current = api.manifest.stat()
    assert (current.st_size, current.st_mtime_ns) == (
        previous.st_size, previous.st_mtime_ns
    ), 'test setup must reproduce a size/mtime collision'
    return updated


@pytest.mark.parametrize('target', ['/chunks', '/chunks?path=src/&limit=1'])
def test_same_size_restored_mtime_returns_current_body_and_etag(api, target):
    first = api.get(target)
    assert first.status == 200
    updated = _replace_preserving_signature(api)

    current = api.get(target)
    assert current.status == 200
    expected = updated if target == '/chunks' else updated[:1]
    assert current.json()['chunks'] == expected, (
        'changed bytes must invalidate the body even when size and mtime match; '
        f'old/new ETags: {first.headers["etag"]}/{current.headers.get("etag")}'
    )
    assert current.headers['etag'] != first.headers['etag']


@pytest.mark.parametrize('target', ['/chunks', '/chunks?path=src/&limit=1'])
def test_same_size_restored_mtime_does_not_return_false_304(api, target):
    first = api.get(target)
    assert first.status == 200
    updated = _replace_preserving_signature(api)

    current = api.get(target, first.headers['etag'])
    assert current.status == 200, 'a changed representation must not revalidate as unchanged'
    assert current.headers['etag'] != first.headers['etag']
    assert current.json()['chunks'] == (updated if target == '/chunks' else updated[:1])


@pytest.mark.parametrize('warm_cache', [False, True], ids=['cold', 'warm'])
@pytest.mark.parametrize(
    'broken',
    [b'{not-json}\n', b'{"path":"src/a.py","anchor":"alpha"}\n{"path":'],
    ids=['malformed', 'truncated-after-valid-row'],
)
def test_invalid_manifest_returns_structured_json_error(api, broken, warm_cache):
    etag = None
    if warm_cache:
        first = api.get()
        assert first.status == 200
        etag = first.headers['etag']
    api.manifest.write_bytes(broken)

    response = api.get(etag=etag)
    assert 500 <= response.status < 600
    payload = response.json()
    assert isinstance(payload, dict)
    assert payload.get('error'), 'manifest parse failure needs a machine-readable error'
    assert 'chunks' not in payload, 'never expose a partially parsed manifest as success'
    assert api.get('/healthz').status == 200


@pytest.mark.parametrize('query', ['offset=not-an-int', 'limit=1.5'])
def test_matching_etag_does_not_bypass_query_validation(api, query):
    first = api.get()
    assert first.status == 200
    target = f'/chunks?{query}'
    invalid = api.get(target)
    assert invalid.status == 400
    assert invalid.json().get('error')

    conditional = api.get(target, first.headers['etag'])
    assert conditional.status == 400, 'validate the query before conditional success'
    assert conditional.json() == invalid.json()


def test_overlapping_cache_publications_never_reuse_etag_for_different_bodies(api, monkeypatch):
    """Pause old full-body serialization while a new request loads a new file.

    A locked implementation may serialize the requests; release the old writer
    after a bounded wait in that case. Never require a particular cache layout.
    """
    old_serializing = threading.Event()
    new_serializing = threading.Event()
    release_old = threading.Event()
    updated = [dict(row, anchor='new-generation') for row in _ROWS]
    real_dumps = json.dumps

    def controlled_dumps(payload, *args, **kwargs):
        chunks = payload.get('chunks') if isinstance(payload, dict) else None
        if chunks == _ROWS and not old_serializing.is_set():
            old_serializing.set()
            if not release_old.wait(timeout=_TIMEOUT):
                raise TimeoutError('test did not release old cache serialization')
        elif chunks == updated:
            new_serializing.set()
        return real_dumps(payload, *args, **kwargs)

    # Patch only core's JSON reference, leaving pytest/client JSON untouched.
    controlled_json = SimpleNamespace(**vars(json))
    controlled_json.dumps = controlled_dumps
    monkeypatch.setattr(core, 'json', controlled_json)
    with ThreadPoolExecutor(max_workers=2) as clients:
        first = clients.submit(api.get)
        try:
            assert old_serializing.wait(timeout=2), 'first request never reached serialization'
            previous = api.manifest.stat()
            _write_manifest(api.manifest, updated)
            os.utime(
                api.manifest,
                ns=(previous.st_atime_ns, previous.st_mtime_ns + 2_000_000_000),
            )
            second = clients.submit(api.get)
            if new_serializing.wait(timeout=0.5):
                # Ensure the new response is published before the old writer
                # resumes; otherwise scheduler speed could conceal the race.
                second.result(timeout=2)
        finally:
            release_old.set()
        responses = [first.result(timeout=_TIMEOUT), second.result(timeout=_TIMEOUT)]

    bodies_by_etag = {}
    for response in responses:
        assert response.status == 200
        assert response.json()['chunks'] in (_ROWS, updated)
        etag = response.headers['etag']
        if etag in bodies_by_etag:
            assert response.body == bodies_by_etag[etag], (
                'same URI/ETag described different bodies during overlapping cache '
                'publication; publish chunks, validator, and full body as one snapshot'
            )
        bodies_by_etag[etag] = response.body

    # Settled full and filtered responses must agree on the published generation.
    assert api.get().json()['chunks'] == updated
    assert api.get('/chunks?path=src/&limit=1').json()['chunks'] == updated[:1]
