"""편집 화면 로컬 서버. 127.0.0.1에만 묶고 모든 요청에 열쇠값을 확인한다."""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .doc import EditDoc, EditError
from .queue import AskQueue

_PAGE = Path(__file__).with_name("page.html")


def state_path(copy: Path) -> Path:
    copy = Path(copy)
    return copy.with_name(f"{copy.stem}.서버.json")


def make_server(doc: EditDoc, queue: AskQueue, key: str, *, port: int = 0, idle: float = 7200,
                base_dir: Path | None = None) -> ThreadingHTTPServer:
    pages_dir = Path(tempfile.mkdtemp(prefix="hwpx-edit-pages-"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 조용히
            pass

        def _send(self, status: int, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self, query: dict) -> bool:
            given = urllib.parse.unquote(self.headers.get("X-Key", "")) or query.get("k", [""])[0]
            return secrets.compare_digest(given.encode("utf-8"), key.encode("utf-8"))

        def _route(self, method: str):
            srv.last = time.monotonic()
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)
            if not self._authorized(query):
                return self._send(403, {"error": "열쇠값이 맞지 않아요."})
            try:
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                return self._dispatch(method, url.path, body)
            except EditError as e:
                return self._send(e.status, {"error": str(e)})
            except (KeyError, TypeError, ValueError) as e:
                return self._send(400, {"error": f"요청을 이해하지 못했어요: {e}"})

        def _dispatch(self, method: str, path: str, body: dict):
            if method == "GET" and path == "/":
                return self._send(200, _PAGE.read_bytes(), "text/html; charset=utf-8")
            if method == "GET" and path == "/api/doc":
                return self._send(200, doc.doc())
            if method == "GET" and path == "/api/asks":
                return self._send(200, {"asks": queue.all()})
            if method == "GET" and path.startswith("/pages/"):
                f = pages_dir / Path(path).name
                if not f.is_file():
                    return self._send(404, {"error": "쪽 그림이 없어요."})
                return self._send(200, f.read_bytes(), "image/png")
            if method == "POST" and path == "/api/edit":
                if "r" in body:
                    v = doc.edit_cell(int(body["version"]), int(body["i"]), int(body["r"]), int(body["c"]),
                                      str(body["text"]))
                else:
                    v = doc.edit_para(int(body["version"]), int(body["i"]), str(body["text"]))
                return self._send(200, {"version": v})
            if method == "POST" and path == "/api/ask":
                return self._send(200, doc.ask(queue, int(body["version"]), int(body["start"]), int(body["end"]),
                                               str(body["text"])))
            if method == "POST" and path == "/api/apply":
                return self._send(200, doc.apply(queue, str(body["id"]), str(body["md"]),
                                                 Path(body.get("base_dir") or base_dir or doc.path.parent)))
            if method == "POST" and path == "/api/undo":
                return self._send(200, {"version": doc.undo()})
            if method == "POST" and path == "/api/pages":
                from .. import bridge
                if not bridge.available():
                    raise EditError("한글이 있어야 실제 쪽 모양을 볼 수 있어요.", 400)
                for old in pages_dir.glob("*.png"):
                    old.unlink()
                files = bridge.page_images(doc.path, pages_dir)
                return self._send(200, {"pages": [f"/pages/{f.name}" for f in files]})
            if method == "POST" and path == "/api/stop":
                threading.Thread(target=srv.shutdown, daemon=True).start()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "없는 주소예요."})

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    srv.last = time.monotonic()
    srv.idle = idle
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}/?k={urllib.parse.quote(key)}"
    return srv


def watch_idle(srv: ThreadingHTTPServer, every: float = 60) -> threading.Thread:
    def loop():
        while True:
            time.sleep(every)
            if time.monotonic() - srv.last > srv.idle:
                srv.shutdown()
                return
    th = threading.Thread(target=loop, daemon=True)
    th.start()
    return th


def serve(src: Path, idle: float = 7200) -> None:
    doc = EditDoc(Path(src))
    queue = AskQueue.for_copy(doc.path)
    key = secrets.token_urlsafe(16)
    srv = make_server(doc, queue, key, idle=idle, base_dir=doc.path.parent)
    state = state_path(doc.path)
    state.write_text(json.dumps({"port": srv.server_address[1], "key": key, "pid": os.getpid(), "url": srv.url},
                                ensure_ascii=False), encoding="utf-8")
    watch_idle(srv)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        state.unlink(missing_ok=True)
