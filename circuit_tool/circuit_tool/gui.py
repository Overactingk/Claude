"""간단한 화면: 로컬 웹서버 + 브라우저 (표준 라이브러리만 사용).

python -m circuit_tool gui project.json  →  http://localhost:8765
"""
from __future__ import annotations

import json
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .exporter import export_project
from .model import ATTR_TAGS, Project
from .parts_db import PartsDB
from .report import write_reports
from .verifier import verify

STATIC = Path(__file__).resolve().parent / "static"


def make_handler(project_path: Path, db_dir: str):
    state = {"proj": Project.load(project_path)}
    out_dir = project_path.parent / "out"
    exp_dir = project_path.parent / "export_dxf"

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/project":
                p = state["proj"]
                d = asdict(p)
                d["name"] = project_path.name
                d["attr_tags"] = ATTR_TAGS
                d["labels"] = {k: e.label() for k, e in p.elements.items()}
                self._json(d)
            elif self.path.startswith("/out/"):
                f = out_dir / Path(self.path[5:]).name
                if f.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f"attachment; filename={f.name}")
                    self.end_headers()
                    self.wfile.write(f.read_bytes())
                else:
                    self._send(404, b"not found", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            p = state["proj"]
            if self.path == "/api/item":
                item = p.item(body["id"])
                if item is None:
                    return self._json({"error": "없는 요소"}, 404)
                item.attrs.update({k: str(v).strip() for k, v in body["attrs"].items()})
                p.save(project_path)
                self._json({"ok": True})
            elif self.path == "/api/verify":
                res = verify(p, PartsDB.load(db_dir))
                files = write_reports(res, p.issues, out_dir)
                self._json({"fuse_rows": res.fuse_rows, "wire_rows": res.wire_rows,
                            "issues": [asdict(i) for i in p.issues + res.issues],
                            "traces": res.traces, "files": [f.name for f in files]})
            elif self.path == "/api/export":
                written, issues = export_project(p, exp_dir)
                self._json({"files": [str(w) for w in written], "issues": [asdict(i) for i in issues]})
            else:
                self._send(404, b"not found", "text/plain")

    return H


def serve(project: str, db_dir: str, port: int = 8765) -> None:
    path = Path(project).resolve()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(path, db_dir))
    url = f"http://127.0.0.1:{port}/"
    print(f"{url}  (종료: Ctrl+C)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
