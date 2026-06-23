"""Менеджер чекпоинтов с оптимистичными блокировками."""

import json
import os
import time
from datetime import datetime
from pathlib import Path


class CheckpointConflictError(Exception):
    pass


class CheckpointManager:
    LOCK_TIMEOUT_SECONDS = 300

    def __init__(self, project_path: Path):
        self.path = Path(project_path) / "checkpoints"
        self.path.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.path / ".checkpoint.lock"

    @staticmethod
    def _process_alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _acquire_lock(self):
        lock_data = f"{os.getpid()}\n{time.time()}\n"
        try:
            fd = os.open(str(self.lock_file),
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            try:
                os.write(fd, lock_data.encode("utf-8"))
            finally:
                os.close(fd)
            return
        except FileExistsError:
            try:
                content = self.lock_file.read_text().strip().split('\n')
                pid = int(content[0])
                timestamp = float(content[1]) if len(content) > 1 else 0
            except (ValueError, FileNotFoundError):
                self.lock_file.unlink(missing_ok=True)
                return self._acquire_lock()
            now = time.time()
            lock_age = now - timestamp
            alive = self._process_alive(pid)
            expired = lock_age > self.LOCK_TIMEOUT_SECONDS
            if alive and not expired:
                raise CheckpointConflictError(
                    f"PID {pid} создаёт чекпоинт (возраст: {lock_age:.1f}s)"
                )
            self.lock_file.unlink(missing_ok=True)
            return self._acquire_lock()

    def _release_lock(self):
        self.lock_file.unlink(missing_ok=True)

    def create(self, summary, next_steps, context, git_commit=None):
        self._acquire_lock()
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = "".join(c if c.isalnum() else "_" for c in summary[:30]).lower()
            filename = f"{ts}_{safe}.json"
            checkpoint = {
                "id": filename,
                "timestamp": datetime.now().isoformat(),
                "summary": summary,
                "next_steps": next_steps,
                "git_commit": git_commit or "unknown",
                "context": context
            }
            (self.path / filename).write_text(
                json.dumps(checkpoint, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            latest = self.path / "latest.json"
            if latest.exists() or latest.is_symlink():
                latest.unlink()
            try:
                latest.symlink_to(filename)
            except OSError:
                latest.write_text(filename)
            return checkpoint
        finally:
            self._release_lock()

    def get_latest(self):
        latest = self.path / "latest.json"
        if not latest.exists():
            return None
        try:
            if latest.is_symlink():
                target = latest.readlink()
            else:
                target = Path(latest.read_text().strip())
            return json.loads((self.path / target).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def get_all(self, limit=10):
        files = sorted(self.path.glob("*.json"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        checkpoints = []
        for f in files[:limit]:
            if f.name in ("latest.json", ".checkpoint.lock"):
                continue
            try:
                checkpoints.append(json.loads(f.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return checkpoints
