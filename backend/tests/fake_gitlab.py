"""A small in-process stand-in for the GitLab REST v4 API, enough for the ELM integration tests."""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "glpat-test-token"


class FakeGitLab:
    def __init__(self):
        self.projects = {"42": {"id": 42, "name": "cpu-software", "path_with_namespace": "product-alpha/cpu-software", "default_branch": "main"}}
        self.branches: dict[str, dict[str, dict]] = {"42": {"main": {"name": "main", "default": True, "commit": {"id": "a" * 40, "short_id": "aaaaaaa"}}}}
        self.mrs: dict[str, list[dict]] = {"42": []}
        self.commits: dict[str, dict[str, list[dict]]] = {"42": {"main": []}}
        self.calls: list[tuple[str, str]] = []
        self.down = False
        self.tags: dict[str, dict[str, str]] = {"42": {}}  # tag -> commit sha
        self.pipelines: dict[int, dict] = {}
        self.health_status = 200
        self.health_text = "ok"
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _send(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _route(self, method):
                fake.calls.append((method, self.path))
                if self.path.startswith("/health"):
                    return self._send(fake.health_status, {"status": fake.health_text})
                if fake.down:
                    return self._send(503, {"message": "maintenance"})
                if self.headers.get("PRIVATE-TOKEN") != TOKEN:
                    return self._send(401, {"message": "401 Unauthorized"})
                u = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                path = u.path[len("/api/v4"):]
                if path == "/version":
                    return self._send(200, {"version": "17.5.0-fake"})
                m = re.match(r"^/projects/([^/]+)(/.*)?$", path)
                if not m:
                    return self._send(404, {"message": "404 Not Found"})
                key = urllib.parse.unquote(m.group(1))
                pid = next((k for k, p in fake.projects.items() if key in (k, p["path_with_namespace"])), None)
                if pid is None:
                    return self._send(404, {"message": "404 Project Not Found"})
                rest = m.group(2) or ""
                base = f"http://gitlab.local/{fake.projects[pid]['path_with_namespace']}"
                if rest == "":
                    return self._send(200, {**fake.projects[pid], "web_url": base})
                if rest == "/repository/branches" and method == "GET":
                    s = q.get("search", "")
                    return self._send(200, [{**b, "web_url": f"{base}/-/tree/{b['name']}"} for b in fake.branches[pid].values() if s in b["name"]])
                if rest == "/repository/branches" and method == "POST":
                    name, ref = q["branch"], q["ref"]
                    if name in fake.branches[pid]:
                        return self._send(400, {"message": "Branch already exists"})
                    if ref not in fake.branches[pid]:
                        return self._send(400, {"message": "Invalid reference name"})
                    fake.branches[pid][name] = {"name": name, "default": False, "commit": fake.branches[pid][ref]["commit"]}
                    fake.commits[pid][name] = list(fake.commits[pid].get(ref, []))
                    return self._send(201, {**fake.branches[pid][name], "web_url": f"{base}/-/tree/{name}"})
                mb = re.match(r"^/repository/branches/(.+)$", rest)
                if mb:
                    name = urllib.parse.unquote(mb.group(1))
                    return self._send(200, fake.branches[pid][name]) if name in fake.branches[pid] else self._send(404, {"message": "404 Branch Not Found"})
                mc = re.match(r"^/repository/commits/(.+)$", rest)
                if mc:
                    ref = urllib.parse.unquote(mc.group(1))
                    sha = fake.tags[pid].get(ref) or (fake.branches[pid][ref]["commit"]["id"] if ref in fake.branches[pid] else None)
                    if not sha and re.fullmatch(r"[0-9a-f]{7,40}", ref):
                        sha = ref
                    return self._send(200, {"id": sha, "short_id": sha[:8]}) if sha else self._send(404, {"message": "404 Commit Not Found"})
                if rest == "/pipeline" and method == "POST":
                    pid_n = len(fake.pipelines) + 100
                    fake.pipelines[pid_n] = {"id": pid_n, "status": "running", "ref": body["ref"], "variables": {v["key"]: v["value"] for v in body.get("variables", [])}, "web_url": f"{base}/-/pipelines/{pid_n}"}
                    return self._send(201, fake.pipelines[pid_n])
                mp = re.match(r"^/pipelines/(\d+)$", rest)
                if mp:
                    pl = fake.pipelines.get(int(mp.group(1)))
                    return self._send(200, pl) if pl else self._send(404, {"message": "404 Not found"})
                if rest == "/repository/commits":
                    return self._send(200, fake.commits[pid].get(q.get("ref_name", "main"), []))
                if rest == "/repository/compare":
                    return self._send(200, {"commits": fake.commits[pid].get(q["to"], []), "diffs": [{"old_path": "src/a.c", "new_path": "src/a.c", "diff": "@@ -1 +1 @@\n-x\n+y\n"}], "web_url": f"{base}/-/compare"})
                if rest == "/merge_requests" and method == "GET":
                    rows = [x for x in fake.mrs[pid] if not q.get("source_branch") or x["source_branch"] == q["source_branch"]]
                    return self._send(200, rows)
                if rest == "/merge_requests" and method == "POST":
                    if body["source_branch"] not in fake.branches[pid]:
                        return self._send(400, {"message": ["Source branch does not exist"]})
                    iid = len(fake.mrs[pid]) + 1
                    mr = {"iid": iid, "title": body["title"], "description": body["description"], "state": "opened", "source_branch": body["source_branch"], "target_branch": body["target_branch"],
                          "web_url": f"{base}/-/merge_requests/{iid}", "author": {"username": "elm-bot"}, "created_at": "2026-11-05T10:00:00Z", "updated_at": "2026-11-05T10:00:00Z"}
                    fake.mrs[pid].append(mr)
                    return self._send(201, mr)
                return self._send(404, {"message": "404 Not Found"})

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add_commit(self, branch: str, sha: str, message: str, pid: str = "42"):
        self.commits[pid].setdefault(branch, []).insert(0, {"id": sha, "short_id": sha[:8], "title": message.split("\n")[0], "message": message, "author_name": "Rakesh Gupta",
                                                             "committed_date": "2026-11-05T11:00:00+05:30", "web_url": f"http://gitlab.local/product-alpha/cpu-software/-/commit/{sha}"})

    def stop(self):
        self.server.shutdown()
