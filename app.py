import csv
import io
import json
import os
import secrets
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
PUBLIC = ROOT / "public"
DB_PATH = ROOT / "hack_crack.db"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin-secret")
HOST, PORT = "0.0.0.0", int(os.getenv("PORT", "8080"))


def db_conn():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def utc_now():
    return datetime.utcnow().isoformat()


def send_json(handler, status, payload):
    data = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def send_text(handler, status, payload, content_type="text/plain"):
    data = payload.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_json(handler):
    size = int(handler.headers.get("Content-Length", "0"))
    if size == 0:
        return {}
    try:
        return json.loads(handler.rfile.read(size).decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def get_auth_token(handler):
    return handler.headers.get("Authorization", "").replace("Bearer ", "").strip()


def get_user_by_token(token):
    if not token:
        return None
    connection = db_conn()
    user = connection.execute(
        """
        SELECT u.*, s.token as session_token
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ?
        """,
        (token,),
    ).fetchone()
    connection.close()
    return user


def require_admin(handler):
    return handler.headers.get("X-Admin-Token", "") == ADMIN_TOKEN


def init_db():
    connection = db_conn()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'player',
            current_level INTEGER DEFAULT 1,
            score INTEGER DEFAULT 0,
            solved INTEGER DEFAULT 0,
            total_time INTEGER DEFAULT 0,
            tab_switches INTEGER DEFAULT 0,
            cheat_flags INTEGER DEFAULT 0,
            disqualified INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY,
            status TEXT DEFAULT 'stopped',
            level INTEGER DEFAULT 1,
            ends_at INTEGER DEFAULT 0,
            started_at INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level INTEGER NOT NULL,
            title TEXT NOT NULL,
            qtype TEXT NOT NULL,
            statement TEXT NOT NULL,
            sample_input TEXT DEFAULT '',
            sample_output TEXT DEFAULT '',
            difficulty TEXT DEFAULT 'medium'
        );

        CREATE TABLE IF NOT EXISTS test_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            input_data TEXT DEFAULT '',
            expected_output TEXT NOT NULL,
            hidden INTEGER DEFAULT 1,
            FOREIGN KEY(question_id) REFERENCES questions(id)
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            code TEXT NOT NULL,
            verdict TEXT NOT NULL,
            points INTEGER NOT NULL,
            exec_time INTEGER NOT NULL,
            created_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(question_id) REFERENCES questions(id)
        );

        CREATE TABLE IF NOT EXISTS badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        INSERT OR IGNORE INTO rounds(id, status, level, ends_at, started_at)
        VALUES(1, 'stopped', 1, 0, 0);

        INSERT OR IGNORE INTO users(username, password, role, created_at)
        VALUES('admin', 'admin123', 'admin', 'seed');
        """
    )

    question_count = connection.execute("SELECT COUNT(*) as c FROM questions").fetchone()["c"]
    if question_count == 0:
        seeds = [
            (
                1,
                "Firewall Breach: Pair Sum",
                "DSA",
                "Given n and n integers, print their sum.",
                "4\n1 2 3 4",
                "10",
                "easy",
                [("4\n1 2 3 4", "10")],
            ),
            (
                2,
                "Algorithm Labyrinth: Reverse Cipher",
                "DSA",
                "Given a string, print it reversed.",
                "hack",
                "kcah",
                "medium",
                [("binary", "yranib")],
            ),
            (
                3,
                "Core System Hack: Grid Paths",
                "Scenario",
                "Read n and m, print n*m.",
                "6 7",
                "42",
                "hard",
                [("6 7", "42")],
            ),
        ]
        for level, title, qtype, statement, sample_input, sample_output, difficulty, tests in seeds:
            cursor = connection.execute(
                """
                INSERT INTO questions(level, title, qtype, statement, sample_input, sample_output, difficulty)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (level, title, qtype, statement, sample_input, sample_output, difficulty),
            )
            question_id = cursor.lastrowid
            for test_input, test_output in tests:
                connection.execute(
                    "INSERT INTO test_cases(question_id, input_data, expected_output, hidden) VALUES (?, ?, ?, 1)",
                    (question_id, test_input, test_output),
                )

    connection.commit()
    connection.close()


def normalize_output(value):
    return "\n".join([line.rstrip() for line in value.strip().splitlines()]).strip()


def run_code(language, code, stdin_text):
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        timeout_s = 3
        compile_time_ms = 0

        if language == "python":
            source = temp_path / "main.py"
            source.write_text(code)
            cmd = ["python3", str(source)]
        elif language == "javascript":
            source = temp_path / "main.js"
            source.write_text(code)
            cmd = ["node", str(source)]
        elif language == "c":
            source = temp_path / "main.c"
            binary = temp_path / "main"
            source.write_text(code)
            t0 = time.time()
            subprocess.run(["gcc", str(source), "-O2", "-o", str(binary)], check=True, capture_output=True, timeout=timeout_s)
            compile_time_ms = int((time.time() - t0) * 1000)
            cmd = [str(binary)]
        elif language == "cpp":
            source = temp_path / "main.cpp"
            binary = temp_path / "main"
            source.write_text(code)
            t0 = time.time()
            subprocess.run(["g++", str(source), "-O2", "-o", str(binary)], check=True, capture_output=True, timeout=timeout_s)
            compile_time_ms = int((time.time() - t0) * 1000)
            cmd = [str(binary)]
        elif language == "java":
            source = temp_path / "Main.java"
            source.write_text(code)
            t0 = time.time()
            subprocess.run(["javac", str(source)], check=True, capture_output=True, timeout=timeout_s)
            compile_time_ms = int((time.time() - t0) * 1000)
            cmd = ["java", "-cp", str(temp_path), "Main"]
        else:
            return {"ok": False, "error": "Unsupported language", "output": "", "exec_ms": 0}

        t1 = time.time()
        proc = subprocess.run(cmd, input=stdin_text.encode("utf-8"), capture_output=True, timeout=timeout_s)
        run_time_ms = int((time.time() - t1) * 1000)
        return {
            "ok": proc.returncode == 0,
            "error": proc.stderr.decode("utf-8")[:4000],
            "output": proc.stdout.decode("utf-8"),
            "exec_ms": compile_time_ms + run_time_ms,
        }


def score_for_submission(connection, user_id, question_id, accepted, total_exec_ms):
    points = -5
    if accepted:
        points = 100
        if total_exec_ms <= 800:
            points += 50
        first_solver = connection.execute(
            "SELECT 1 FROM submissions WHERE question_id=? AND verdict='Accepted' LIMIT 1",
            (question_id,),
        ).fetchone()
        if not first_solver:
            points += 75

    connection.execute(
        """
        UPDATE users
        SET score = score + ?,
            solved = solved + ?,
            total_time = total_time + ?
        WHERE id = ?
        """,
        (points, 1 if accepted else 0, total_exec_ms, user_id),
    )

    refreshed = connection.execute("SELECT score, current_level FROM users WHERE id=?", (user_id,)).fetchone()
    if refreshed["score"] >= 300 and refreshed["current_level"] < 2:
        connection.execute("UPDATE users SET current_level=2 WHERE id=?", (user_id,))
        connection.execute("INSERT OR IGNORE INTO badges(user_id, name) VALUES(?, ?)", (user_id, "Firewall Breacher"))
    if refreshed["score"] >= 700 and refreshed["current_level"] < 3:
        connection.execute("UPDATE users SET current_level=3 WHERE id=?", (user_id,))
        connection.execute("INSERT OR IGNORE INTO badges(user_id, name) VALUES(?, ?)", (user_id, "Algorithm Escapee"))

    return points


class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Admin-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            return self.handle_api_get(parsed)

        target = PUBLIC / ("index.html" if parsed.path == "/" else parsed.path.lstrip("/"))
        if target.exists() and target.is_file():
            content_type = "text/plain"
            if target.suffix == ".html":
                content_type = "text/html"
            elif target.suffix == ".css":
                content_type = "text/css"
            elif target.suffix == ".js":
                content_type = "application/javascript"
            send_text(self, 200, target.read_text(), content_type=content_type)
            return

        send_json(self, 404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return send_json(self, 404, {"error": "Not found"})
        self.handle_api_post(parsed)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return send_json(self, 404, {"error": "Not found"})
        self.handle_api_put(parsed)

    def handle_api_get(self, parsed):
        token = get_auth_token(self)
        user = get_user_by_token(token)
        connection = db_conn()

        if parsed.path == "/api/leaderboard":
            rows = connection.execute(
                """
                SELECT username, score, solved, total_time, current_level
                FROM users
                WHERE role='player'
                ORDER BY score DESC, solved DESC, total_time ASC
                """
            ).fetchall()
            send_json(self, 200, [{"rank": idx + 1, **dict(row)} for idx, row in enumerate(rows)])
            connection.close()
            return

        if parsed.path == "/api/round":
            state = connection.execute("SELECT status, level, ends_at, started_at FROM rounds WHERE id=1").fetchone()
            send_json(self, 200, dict(state))
            connection.close()
            return

        if parsed.path == "/api/me":
            if not user:
                connection.close()
                return send_json(self, 401, {"error": "Unauthorized"})
            badges = [r["name"] for r in connection.execute("SELECT name FROM badges WHERE user_id=?", (user["id"],)).fetchall()]
            payload = {
                "username": user["username"],
                "role": user["role"],
                "score": user["score"],
                "solved": user["solved"],
                "total_time": user["total_time"],
                "current_level": user["current_level"],
                "tab_switches": user["tab_switches"],
                "cheat_flags": user["cheat_flags"],
                "disqualified": user["disqualified"],
                "badges": badges,
            }
            send_json(self, 200, payload)
            connection.close()
            return

        if parsed.path == "/api/questions":
            if not user:
                connection.close()
                return send_json(self, 401, {"error": "Unauthorized"})
            params = parse_qs(parsed.query)
            requested_level = int(params.get("level", [str(user["current_level"])])[0])
            if user["role"] != "admin" and requested_level > user["current_level"]:
                connection.close()
                return send_json(self, 403, {"error": "Level locked"})
            rows = connection.execute(
                """
                SELECT id, level, title, qtype, statement, sample_input, sample_output, difficulty
                FROM questions WHERE level=? ORDER BY id
                """,
                (requested_level,),
            ).fetchall()
            send_json(self, 200, [dict(row) for row in rows])
            connection.close()
            return

        if parsed.path == "/api/admin/submissions":
            if not require_admin(self):
                connection.close()
                return send_json(self, 403, {"error": "Forbidden"})
            rows = connection.execute(
                """
                SELECT s.id, u.username, s.question_id, s.language, s.verdict, s.points, s.exec_time, s.created_at
                FROM submissions s
                JOIN users u ON u.id = s.user_id
                ORDER BY s.id DESC LIMIT 300
                """
            ).fetchall()
            send_json(self, 200, [dict(row) for row in rows])
            connection.close()
            return

        if parsed.path == "/api/admin/export":
            if not require_admin(self):
                connection.close()
                return send_json(self, 403, {"error": "Forbidden"})
            rows = connection.execute(
                "SELECT username, score, solved, total_time, current_level, disqualified FROM users WHERE role='player' ORDER BY score DESC"
            ).fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["username", "score", "solved", "total_time", "current_level", "disqualified"])
            for row in rows:
                writer.writerow([row["username"], row["score"], row["solved"], row["total_time"], row["current_level"], row["disqualified"]])
            send_text(self, 200, output.getvalue(), content_type="text/csv")
            connection.close()
            return

        send_json(self, 404, {"error": "Unknown endpoint"})
        connection.close()

    def handle_api_post(self, parsed):
        body = read_json(self)
        connection = db_conn()

        if parsed.path == "/api/login":
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", "")).strip()
            user = connection.execute(
                "SELECT * FROM users WHERE username=? AND password=?",
                (username, password),
            ).fetchone()
            if not user:
                connection.close()
                return send_json(self, 401, {"error": "Invalid credentials"})
            if user["disqualified"]:
                connection.close()
                return send_json(self, 403, {"error": "Disqualified"})

            # enforce one active session
            connection.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            token = secrets.token_hex(24)
            connection.execute(
                "INSERT INTO sessions(token, user_id, created_at) VALUES (?, ?, ?)",
                (token, user["id"], utc_now()),
            )
            connection.commit()
            connection.close()
            return send_json(self, 200, {"token": token, "role": user["role"]})

        token = get_auth_token(self)
        user = get_user_by_token(token)

        if parsed.path == "/api/logout":
            if user:
                connection.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
                connection.commit()
            connection.close()
            return send_json(self, 200, {"ok": True})

        if not user:
            connection.close()
            return send_json(self, 401, {"error": "Unauthorized"})

        if user["disqualified"]:
            connection.close()
            return send_json(self, 403, {"error": "Disqualified"})

        if parsed.path == "/api/submit":
            question_id = int(body.get("question_id", 0))
            language = str(body.get("language", ""))
            code = str(body.get("code", ""))
            if not question_id or not language or not code:
                connection.close()
                return send_json(self, 400, {"error": "Missing required fields"})

            round_state = connection.execute("SELECT * FROM rounds WHERE id=1").fetchone()
            now_ts = int(time.time())
            if round_state["status"] != "running" or now_ts > round_state["ends_at"]:
                connection.close()
                return send_json(self, 403, {"error": "Round not active"})

            question = connection.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
            if not question:
                connection.close()
                return send_json(self, 404, {"error": "Question not found"})
            if user["role"] != "admin" and question["level"] > user["current_level"]:
                connection.close()
                return send_json(self, 403, {"error": "Level locked"})

            tests = connection.execute(
                "SELECT input_data, expected_output FROM test_cases WHERE question_id=?",
                (question_id,),
            ).fetchall()

            accepted = True
            total_exec_ms = 0
            fail_reason = ""
            try:
                for test in tests:
                    result = run_code(language, code, test["input_data"])
                    total_exec_ms += result["exec_ms"]
                    if not result["ok"]:
                        accepted = False
                        fail_reason = "Runtime/Compile Error"
                        break
                    if normalize_output(result["output"]) != normalize_output(test["expected_output"]):
                        accepted = False
                        fail_reason = "Wrong Answer"
                        break
            except subprocess.TimeoutExpired:
                accepted = False
                fail_reason = "Time Limit Exceeded"
            except Exception:
                accepted = False
                fail_reason = "Judge Failure"

            points = score_for_submission(connection, user["id"], question_id, accepted, total_exec_ms)
            verdict = "Accepted" if accepted else fail_reason
            connection.execute(
                """
                INSERT INTO submissions(user_id, question_id, language, code, verdict, points, exec_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user["id"], question_id, language, code, verdict, points, total_exec_ms, utc_now()),
            )
            connection.commit()
            connection.close()
            return send_json(self, 200, {"verdict": verdict, "points": points, "exec_ms": total_exec_ms})

        if parsed.path == "/api/anti-cheat":
            tab_switches = int(body.get("tab_switches", 0))
            cheat_flags = int(body.get("cheat_flags", 0))
            devtools = bool(body.get("devtools", False))
            shortcut_attempt = bool(body.get("shortcut_attempt", False))

            total_flags = cheat_flags + (1 if devtools else 0) + (1 if shortcut_attempt else 0)
            should_disqualify = tab_switches > 3 or total_flags >= 5

            connection.execute(
                "UPDATE users SET tab_switches=?, cheat_flags=?, disqualified=? WHERE id=?",
                (tab_switches, total_flags, 1 if should_disqualify else user["disqualified"], user["id"]),
            )
            connection.commit()
            connection.close()
            return send_json(self, 200, {"disqualified": bool(should_disqualify)})

        if parsed.path == "/api/admin/generate-users":
            if not require_admin(self):
                connection.close()
                return send_json(self, 403, {"error": "Forbidden"})

            count = max(1, min(100, int(body.get("count", 10))))
            prefix = str(body.get("prefix", "player")).strip() or "player"
            generated = []
            stamp = int(time.time())
            for i in range(count):
                username = f"{prefix}{stamp}{i:02d}"
                password = secrets.token_hex(3)
                connection.execute(
                    "INSERT INTO users(username, password, role, created_at) VALUES (?, ?, 'player', ?)",
                    (username, password, utc_now()),
                )
                generated.append({"username": username, "password": password})
            connection.commit()
            connection.close()
            return send_json(self, 200, generated)

        if parsed.path == "/api/admin/questions":
            if not require_admin(self):
                connection.close()
                return send_json(self, 403, {"error": "Forbidden"})

            level = int(body.get("level", 1))
            cursor = connection.execute(
                """
                INSERT INTO questions(level, title, qtype, statement, sample_input, sample_output, difficulty)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    level,
                    str(body.get("title", "Untitled")),
                    str(body.get("qtype", "DSA")),
                    str(body.get("statement", "")),
                    str(body.get("sample_input", "")),
                    str(body.get("sample_output", "")),
                    str(body.get("difficulty", "medium")),
                ),
            )
            question_id = cursor.lastrowid
            for testcase in body.get("test_cases", []):
                connection.execute(
                    "INSERT INTO test_cases(question_id, input_data, expected_output, hidden) VALUES (?, ?, ?, 1)",
                    (question_id, str(testcase.get("input", "")), str(testcase.get("output", ""))),
                )
            connection.commit()
            connection.close()
            return send_json(self, 200, {"ok": True, "id": question_id})

        if parsed.path == "/api/admin/round":
            if not require_admin(self):
                connection.close()
                return send_json(self, 403, {"error": "Forbidden"})

            status = str(body.get("status", "running"))
            level = int(body.get("level", 1))
            duration = max(60, int(body.get("duration_sec", 1800)))
            now_ts = int(time.time())
            ends_at = now_ts + duration if status == "running" else 0
            started_at = now_ts if status == "running" else 0
            connection.execute(
                "UPDATE rounds SET status=?, level=?, ends_at=?, started_at=? WHERE id=1",
                (status, level, ends_at, started_at),
            )
            connection.commit()
            connection.close()
            return send_json(self, 200, {"status": status, "level": level, "ends_at": ends_at, "started_at": started_at})

        connection.close()
        send_json(self, 404, {"error": "Unknown endpoint"})

    def handle_api_put(self, parsed):
        if parsed.path != "/api/admin/questions":
            return send_json(self, 404, {"error": "Unknown endpoint"})
        if not require_admin(self):
            return send_json(self, 403, {"error": "Forbidden"})

        body = read_json(self)
        question_id = int(body.get("id", 0))
        if not question_id:
            return send_json(self, 400, {"error": "Question id required"})

        connection = db_conn()
        current = connection.execute("SELECT id FROM questions WHERE id=?", (question_id,)).fetchone()
        if not current:
            connection.close()
            return send_json(self, 404, {"error": "Question not found"})

        connection.execute(
            """
            UPDATE questions
            SET level=?, title=?, qtype=?, statement=?, sample_input=?, sample_output=?, difficulty=?
            WHERE id=?
            """,
            (
                int(body.get("level", 1)),
                str(body.get("title", "Untitled")),
                str(body.get("qtype", "DSA")),
                str(body.get("statement", "")),
                str(body.get("sample_input", "")),
                str(body.get("sample_output", "")),
                str(body.get("difficulty", "medium")),
                question_id,
            ),
        )
        if "test_cases" in body:
            connection.execute("DELETE FROM test_cases WHERE question_id=?", (question_id,))
            for testcase in body.get("test_cases", []):
                connection.execute(
                    "INSERT INTO test_cases(question_id, input_data, expected_output, hidden) VALUES (?, ?, ?, 1)",
                    (question_id, str(testcase.get("input", "")), str(testcase.get("output", ""))),
                )

        connection.commit()
        connection.close()
        send_json(self, 200, {"ok": True})


if __name__ == "__main__":
    PUBLIC.mkdir(exist_ok=True)
    init_db()
    print(f"Hack & Crack server running on http://{HOST}:{PORT}")
    HTTPServer((HOST, PORT), Handler).serve_forever()
