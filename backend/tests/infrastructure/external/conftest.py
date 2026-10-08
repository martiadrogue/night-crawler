import json
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from browser_use import Tools
from browser_use.agent.views import AgentHistoryList, AgentOutput

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
        if "/challenge" == self.path:
            # Like a bot check: until the cookie is set, a page that sets
            # it and reloads itself a moment later.
            if "cleared=1" in self.headers.get("Cookie", ""):
                body = b"<html><body><p id='state'>passed</p></body></html>"
            else:
                body = (
                    b"<html><body><p id='state'>challenge</p><script>"
                    b"setTimeout(function () {"
                    b" document.cookie = 'cleared=1; path=/'; location.reload();"
                    b" }, 700)</script></body></html>"
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


@pytest.fixture
def load_history():
    """Return a loader of the recorded Browser Use history.

    It is parsed by Browser Use's own models, as the agent returns it;
    `item_count` keeps only the first items, as a run cut short would.
    """
    fixture = Path(__file__).parent / "fixtures" / "browser_use" / "agent_history.json"
    output_model = AgentOutput.type_with_custom_actions(
        Tools().registry.create_action_model()
    )

    def _load(item_count: int | None = None) -> AgentHistoryList:
        data = json.loads(fixture.read_text())
        data["history"] = data["history"][:item_count]
        return AgentHistoryList.load_from_dict(data, output_model)

    return _load
