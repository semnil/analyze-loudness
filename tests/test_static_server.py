"""The static server serves initial assets in bounded connection bursts."""

from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from http.server import HTTPServer
from pathlib import Path
import socket
import threading
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

from tests.test_frontend import _test_server

_MAX_CONNECTIONS = 6


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attributes):
        if tag == "script":
            source = dict(attributes).get("src")
            if source:
                self.sources.append(source)


def test_initial_assets_survive_a_queued_connection_burst(_test_server, monkeypatch):
    root = Path(__file__).resolve().parent.parent
    document = "/tests/frontend/test_ui.html"
    scripts = _Scripts()
    scripts.feed((root / document.lstrip("/")).read_text(encoding="utf-8"))
    assert scripts.sources
    with urlopen(f"http://127.0.0.1:{_test_server}{document}", timeout=5) as response:
        assert response.status == 200
        assert response.read() == (root / document.lstrip("/")).read_bytes()
    paths = [urljoin(document, source) for source in scripts.sources]
    accept_waiting = threading.Event()
    release = threading.Event()
    original = HTTPServer.get_request

    def hold_accept(server):
        if server.server_port == _test_server and not accept_waiting.is_set():
            accept_waiting.set()
            if not release.wait(5):
                raise AssertionError("Initial asset connections were not released")
        return original(server)

    monkeypatch.setattr(HTTPServer, "get_request", hold_accept)
    clients = []
    try:
        def receive(client):
            with client.makefile("rb") as response:
                return response.read()

        for start in range(0, len(paths), _MAX_CONNECTIONS):
            batch = paths[start:start + _MAX_CONNECTIONS]
            for path in batch:
                client = socket.socket()
                clients.append(client)
                client.settimeout(5)
                client.connect(("127.0.0.1", _test_server))
                client.sendall(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode("ascii"))
                if start == 0 and len(clients) == 1:
                    assert accept_waiting.wait(5)
            release.set()

            with ThreadPoolExecutor(max_workers=len(clients)) as pool:
                responses = list(pool.map(receive, clients))
            for path, response in zip(batch, responses):
                headers, body = response.split(b"\r\n\r\n", 1)
                assert headers.startswith(b"HTTP/1.0 200 ")
                assert body == (root / urlsplit(path).path.lstrip("/")).read_bytes()
            for client in clients:
                client.close()
            clients.clear()
    finally:
        release.set()
        for client in clients:
            client.close()
