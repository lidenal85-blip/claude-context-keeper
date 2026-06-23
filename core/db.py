"""SQLite с WAL mode, атомарным fallback и автоочисткой."""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path


class StateDB:
    WAL_SIZE_LIMIT = 10 * 1024 * 1024

    def __init__(self, project_path: Path):
        self.project_path = Path(project_path)
        self.db_path = self.project_path / "logs" / "state.db"
        self.pending_path = self.project_path / "logs" / "pending.jsonl"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    details_json TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    summary TEXT,
                    next_steps_json TEXT DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    question TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reasoning TEXT
                );
                CREATE TABLE IF NOT EXISTS invariants (
                    category TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    PRIMARY KEY (category, pattern)
                );
                CREATE INDEX IF NOT EXISTS idx_actions_timestamp ON actions(timestamp);
                CREATE INDEX IF NOT EXISTS idx_actions_task ON actions(task_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            """)

    def _connect(self):
        return sqlite3.connect(str(self.db_path), timeout=10)

    def _write_pending(self, record: dict):
        line = json.dumps(record, ensure_ascii=False) + "\n"
        fd = os.open(str(self.pending_path),
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def _maybe_checkpoint_wal(self):
        wal_path = self.db_path.with_suffix(".db-wal")
        try:
            if not wal_path.exists():
                return
            if wal_path.stat().st_size > self.WAL_SIZE_LIMIT:
                with sqlite3.connect(str(self.db_path), timeout=10) as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except (OSError, sqlite3.Error):
            pass

    def log_action(self, task_id, action_type, description, details=None):
        record = {
            "timestamp": datetime.now().isoformat(),
            "task_id": task_id,
            "action_type": action_type,
            "description": description,
            "details": details or {}
        }
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO actions (timestamp, task_id, action_type, "
                    "description, details_json) VALUES (?, ?, ?, ?, ?)",
                    (record["timestamp"], task_id, action_type,
                     description, json.dumps(details or {}, ensure_ascii=False))
                )
            self._maybe_checkpoint_wal()
        except sqlite3.OperationalError:
            self._write_pending(record)

    def register_task(self, task_id, name):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tasks (id, name, started_at, status) "
                "VALUES (?, ?, ?, 'active')",
                (task_id, name, datetime.now().isoformat())
            )

    def complete_task(self, task_id, summary, next_steps=None):
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status='completed', completed_at=?, "
                "summary=?, next_steps_json=? WHERE id=?",
                (datetime.now().isoformat(), summary,
                 json.dumps(next_steps or [], ensure_ascii=False), task_id)
            )

    def detect_stalled_tasks(self, timeout_minutes=30):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, started_at FROM tasks WHERE status='active' "
                "AND started_at < datetime('now', ? || ' minutes')",
                (f"-{timeout_minutes}",)
            ).fetchall()
        return [{"task_id": r[0], "name": r[1], "started_at": r[2]} for r in rows]

    def mark_stalled(self, task_id):
        with self._connect() as conn:
            conn.execute("UPDATE tasks SET status='stalled' WHERE id=?", (task_id,))

    def add_decision(self, category, question, decision, reasoning=None):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO decisions (timestamp, category, question, "
                "decision, reasoning) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().isoformat(), category, question, decision, reasoning)
            )
            conn.execute(
                "INSERT INTO invariants (category, pattern) VALUES (?, ?) "
                "ON CONFLICT(category, pattern) DO UPDATE SET count = count + 1",
                (category, decision)
            )

    def get_context(self, limit=20):
        with self._connect() as conn:
            actions = conn.execute(
                "SELECT action_type, description, timestamp FROM actions "
                "ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            decisions = conn.execute(
                "SELECT category, question, decision FROM decisions "
                "ORDER BY timestamp DESC LIMIT 10"
            ).fetchall()
            invariants = conn.execute(
                "SELECT category, pattern, count FROM invariants "
                "WHERE count >= 2 ORDER BY count DESC"
            ).fetchall()
            stalled = conn.execute(
                "SELECT id, name FROM tasks WHERE status='stalled'"
            ).fetchall()
        return {
            "recent_actions": [{"type": a[0], "description": a[1],
                                "timestamp": a[2]} for a in actions],
            "recent_decisions": [{"category": d[0], "question": d[1],
                                  "decision": d[2]} for d in decisions],
            "invariants": [{"category": i[0], "pattern": i[1],
                            "count": i[2]} for i in invariants],
            "stalled_tasks": [{"task_id": s[0], "name": s[1]} for s in stalled]
        }

    def recover_wal(self):
        if not self.pending_path.exists():
            return 0
        recovered = 0
        corrupted = 0
        valid_lines = []
        with open(self.pending_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if all(k in record for k in
                           ("timestamp", "task_id", "action_type", "description")):
                        valid_lines.append(record)
                    else:
                        corrupted += 1
                except json.JSONDecodeError:
                    corrupted += 1
        if corrupted > 0:
            print(f"[claude-logger] Warning: {corrupted} corrupted lines")
        if not valid_lines:
            self.pending_path.unlink(missing_ok=True)
            return 0
        with self._connect() as conn:
            for record in valid_lines:
                try:
                    conn.execute(
                        "INSERT INTO actions (timestamp, task_id, action_type, "
                        "description, details_json) VALUES (?, ?, ?, ?, ?)",
                        (record["timestamp"], record["task_id"],
                         record["action_type"], record["description"],
                         json.dumps(record.get("details", {}), ensure_ascii=False))
                    )
                    recovered += 1
                except sqlite3.Error:
                    continue
        backup = self.pending_path.with_suffix(".jsonl.recovered")
        self.pending_path.rename(backup)
        backup.unlink(missing_ok=True)
        return recovered
