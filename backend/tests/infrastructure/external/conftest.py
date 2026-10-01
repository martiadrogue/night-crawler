import json
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

_ECHO_PAGE = """<html><body>
<p id="cookie">{cookie}</p><p id="custom">{custom}</p><p id="ua">{ua}</p>
<p id="panel">empty</p>
<button class="tab" onclick="document.getElementById('panel').textContent='Menu'">
  menu</button>
<button class="tab" onclick="document.getElementById('panel').textContent='Reviews'">
  reviews</button>
</body></html>"""


class _EchoHandler(BaseHTTPRequestHandler):
    """Echo the received cookies and headers, and set a cookie."""

    def do_GET(self) -> None:
        if "/session/start" == self.path:
            body = (
                b"<html><body><script>"
                b"sessionStorage.setItem('crawler-session', 'retained')"
                b"</script></body></html>"
            )
            self._reply("text/html", body)
            return
        if "/session/check" == self.path:
            body = (
                b"<html><body><p id='state'></p><script>"
                b"document.querySelector('#state').textContent = "
                b"sessionStorage.getItem('crawler-session') || 'empty'"
                b"</script></body></html>"
            )
            self._reply("text/html", body)
            return
        if "/json" == self.path:
            body = json.dumps(
                {
                    "pageProps": {
                        "searchPageResultsFetchResult": {
                            "pagination": {"hasNext": True, "currentPage": 17}
                        }
                    }
                }
            ).encode()
            self._reply("application/json; charset=utf-8", body)
            return
        body = _ECHO_PAGE.format(
            cookie=self.headers.get("Cookie", ""),
            custom=self.headers.get("X-Custom", ""),
            ua=self.headers.get("User-Agent", ""),
        ).encode()
        self._reply("text/html", body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        received = json.loads(self.rfile.read(length) or b"{}")
        body = json.dumps(
            {"received": received, "custom": self.headers.get("X-Custom", "")}
        ).encode()
        self._reply("application/json", body)

    def _reply(self, content_type: str, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Set-Cookie", "server=1; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture(scope="module")
def echo_server() -> Generator[str, None, None]:
    """A local HTTP server echoing what it receives; yields its URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
