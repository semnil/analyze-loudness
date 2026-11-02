"""The static server accepts the harness's initial asset requests together."""

from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from http.server import HTTPServer
from pathlib import Path
import socket
import threading
from urllib.parse import urljoin, urlsplit

from tests.test_frontend import _test_server


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
    paths = [document] + [urljoin(document, source) for source in scripts.sources]
    accepted = threading.Event()
    release = threading.Event()
    original = HTTPServer.get_request

    def hold_accept(server):
        connection = original(server)
        if server.server_port == _test_server and not accepted.is_set():
            accepted.set()
            if not release.wait(5):
                connection[0].close()
                raise AssertionError("Initial asset connections were not released")
        return connection

    monkeypatch.setattr(HTTPServer, "get_request", hold_accept)
    clients = []
    try:
        for index, path in enumerate(paths):
            client = socket.socket()
            clients.append(client)
            client.settimeout(5)
            client.connect(("127.0.0.1", _test_server))
            client.sendall(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode("ascii"))
            if index == 0:
                assert accepted.wait(5)
        release.set()

        def receive(client):
            with client.makefile("rb") as response:
                return response.read()

        with ThreadPoolExecutor(max_workers=len(clients)) as pool:
            responses = list(pool.map(receive, clients))
        for path, response in zip(paths, responses):
            headers, body = response.split(b"\r\n\r\n", 1)
            assert headers.startswith(b"HTTP/1.0 200 ")
            assert body == (root / urlsplit(path).path.lstrip("/")).read_bytes()
    finally:
        release.set()
        for client in clients:
            client.close()
