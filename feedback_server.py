"""
CrediGraph Feedback Backend v2
- User system (simple name-based, stored in DB)
- Feedback with correction labels (credible / not credible)
- Export CSV / JSON

Usage: python feedback_server.py [--port 8081]
"""
import csv
import io
import json
import sqlite3
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback.db")
PORT = 8081


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL,
            vote TEXT NOT NULL CHECK(vote IN ('up', 'down')),
            correction TEXT CHECK(correction IN ('credible', 'not_credible', NULL)),
            model_prediction TEXT,
            user_id INTEGER,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()


def json_response(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler._cors()
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class FeedbackHandler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    # ── POST routes ──────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/user":
            body = self._read_json()
            username = (body.get("username") or "").strip()
            if not username:
                return json_response(self, {"error": "username required"}, 400)
            conn = get_db()
            try:
                conn.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
                conn.commit()
                row = conn.execute("SELECT id, username, created_at FROM users WHERE username=?", (username,)).fetchone()
                return json_response(self, {"id": row["id"], "username": row["username"], "created_at": row["created_at"]})
            finally:
                conn.close()

        elif path == "/feedback":
            body = self._read_json()
            domain = (body.get("domain") or "").strip()
            vote = (body.get("vote") or "").strip()
            correction = body.get("correction")  # "credible" | "not_credible" | null
            model_prediction = body.get("model_prediction")
            user_id = body.get("user_id")
            ts = body.get("timestamp", datetime.utcnow().isoformat())

            if not domain or vote not in ("up", "down"):
                return json_response(self, {"error": "domain and vote(up/down) required"}, 400)
            if correction and correction not in ("credible", "not_credible"):
                return json_response(self, {"error": "correction must be credible or not_credible"}, 400)

            conn = get_db()
            try:
                cur = conn.execute(
                    "INSERT INTO feedback (domain, vote, correction, model_prediction, user_id, timestamp) VALUES (?,?,?,?,?,?)",
                    (domain, vote, correction, model_prediction, user_id, ts),
                )
                conn.commit()
                return json_response(self, {"ok": True, "id": cur.lastrowid})
            finally:
                conn.close()

        else:
            json_response(self, {"error": "not found"}, 404)

    # ── GET routes ───────────────────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/feedback":
            conn = get_db()
            rows = conn.execute("""
                SELECT f.id, f.domain, f.vote, f.correction, f.model_prediction,
                       f.user_id, u.username, f.timestamp, f.created_at
                FROM feedback f LEFT JOIN users u ON f.user_id = u.id
                ORDER BY f.id DESC LIMIT 1000
            """).fetchall()
            conn.close()
            data = [dict(r) for r in rows]
            return json_response(self, data)

        elif path == "/feedback/stats":
            conn = get_db()
            rows = conn.execute("""
                SELECT domain,
                       SUM(CASE WHEN vote='up' THEN 1 ELSE 0 END) as upvotes,
                       SUM(CASE WHEN vote='down' THEN 1 ELSE 0 END) as downvotes,
                       SUM(CASE WHEN correction='credible' THEN 1 ELSE 0 END) as labeled_credible,
                       SUM(CASE WHEN correction='not_credible' THEN 1 ELSE 0 END) as labeled_not_credible,
                       COUNT(*) as total
                FROM feedback GROUP BY domain ORDER BY total DESC
            """).fetchall()
            conn.close()
            return json_response(self, [dict(r) for r in rows])

        elif path == "/feedback/export":
            fmt = params.get("format", ["json"])[0]
            conn = get_db()
            rows = conn.execute("""
                SELECT f.id, f.domain, f.vote, f.correction, f.model_prediction,
                       u.username, f.timestamp, f.created_at
                FROM feedback f LEFT JOIN users u ON f.user_id = u.id
                ORDER BY f.id
            """).fetchall()
            conn.close()

            if fmt == "csv":
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["id", "domain", "vote", "correction", "model_prediction", "username", "timestamp", "created_at"])
                for r in rows:
                    writer.writerow([r["id"], r["domain"], r["vote"], r["correction"], r["model_prediction"], r["username"], r["timestamp"], r["created_at"]])
                body = output.getvalue().encode("utf-8")
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=credigraph_feedback.csv")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                data = [dict(r) for r in rows]
                body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=credigraph_feedback.json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        elif path == "/users":
            conn = get_db()
            rows = conn.execute("SELECT id, username, created_at FROM users ORDER BY id").fetchall()
            conn.close()
            return json_response(self, [dict(r) for r in rows])

        else:
            json_response(self, {"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")


if __name__ == "__main__":
    import sys
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else PORT
    init_db()
    print(f"CrediGraph Feedback Server v2")
    print(f"  http://localhost:{port}")
    print(f"  DB: {DB_PATH}")
    print(f"  POST /user           - register/login {{username}}")
    print(f"  POST /feedback       - submit {{domain, vote, correction?, model_prediction?, user_id?}}")
    print(f"  GET  /feedback       - list all")
    print(f"  GET  /feedback/stats - per-domain stats")
    print(f"  GET  /feedback/export?format=csv|json - download")
    print(f"  GET  /users          - list users")
    HTTPServer(("", port), FeedbackHandler).serve_forever()
