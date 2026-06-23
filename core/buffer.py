"""Буферизованный логгер — пачки по 10 действий или раз в 5 секунд."""

import time
from collections import deque

from core.db import StateDB


class BufferedLogger:
    def __init__(self, db: StateDB, flush_threshold=10, flush_interval=5):
        self.db = db
        self.buffer = deque()
        self.threshold = flush_threshold
        self.interval = flush_interval
        self.last_flush = time.time()
        self.current_task_id = None

    def start_task(self, task_name):
        self.current_task_id = (
            f"{int(time.time())}_{task_name[:20].replace(' ', '_')}"
        )
        self.db.register_task(self.current_task_id, task_name)
        self._enqueue("task_started", task_name, {})
        return self.current_task_id

    def log(self, action_type, description, details=None):
        if not self.current_task_id:
            self.start_task("unnamed_task")
        self._enqueue(action_type, description, details or {})

    def log_decision(self, category, question, decision, reasoning=None):
        if not self.current_task_id:
            self.start_task("unnamed_task")
        self._enqueue("decision", f"{category}: {decision}", {
            "category": category, "question": question,
            "decision": decision, "reasoning": reasoning
        })
        self.db.add_decision(category, question, decision, reasoning)

    def _enqueue(self, action_type, description, details):
        self.buffer.append({
            "task_id": self.current_task_id,
            "action_type": action_type,
            "description": description,
            "details": details
        })
        self._maybe_flush()

    def _maybe_flush(self):
        if len(self.buffer) >= self.threshold or (
            time.time() - self.last_flush > self.interval
        ):
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        while self.buffer:
            action = self.buffer.popleft()
            self.db.log_action(**action)
        self.last_flush = time.time()

    def complete_task(self, summary, next_steps=None):
        self._enqueue("task_completed", summary,
                      {"next_steps": next_steps or []})
        self.flush()
        if self.current_task_id:
            self.db.complete_task(self.current_task_id, summary, next_steps)
        task_id = self.current_task_id
        self.current_task_id = None
        return task_id
