"""Экспорт промпт-инъекта для нового аккаунта Claude."""

from core.db import StateDB
from core.git_context import GitContext
from core.checkpoints import CheckpointManager


class PromptExporter:
    def __init__(self, project_path, db: StateDB,
                 git: GitContext, checkpoints: CheckpointManager):
        self.path = project_path
        self.db = db
        self.git = git
        self.checkpoints = checkpoints

    def export(self):
        latest = self.checkpoints.get_latest()
        context = self.db.get_context()
        uncommitted = self.git.get_uncommitted_files()
        prompt = f"""[Контекст проекта из предыдущей сессии]

Проект: {self.path.name}
Git: {self.git.get_current_commit()[:8]}
"""
        if context["stalled_tasks"]:
            prompt += "\n## Прерванные задачи:\n"
            for task in context["stalled_tasks"]:
                prompt += f"- {task['name']}\n"
        if latest:
            prompt += f"""
## Последний чекпоинт
**{latest['summary']}**

Следующие шаги:
"""
            for i, step in enumerate(latest.get("next_steps", []), 1):
                prompt += f"{i}. {step}\n"
        if uncommitted:
            prompt += "\n## Некоммиченные файлы:\n"
            for f in uncommitted[:10]:
                prompt += f"- {f}\n"
        prompt += """
---
Продолжи с последнего чекпоинта. Прочитай .claude/claude.md,
вызови restore_context(). Не пересоздавай файлы без проверки.
"""
        return prompt
