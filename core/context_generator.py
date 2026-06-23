"""Генерация .claude/claude.md из Jinja2-шаблона."""

from datetime import datetime
from pathlib import Path

from jinja2 import Template

from core.db import StateDB
from core.git_context import GitContext
from core.checkpoints import CheckpointManager


class ContextGenerator:
    def __init__(self, project_path: Path, db: StateDB,
                 git: GitContext, checkpoints: CheckpointManager):
        self.path = Path(project_path)
        self.db = db
        self.git = git
        self.checkpoints = checkpoints
        self.template_path = self.path / ".claude" / "claude.template.md"
        self.output_path = self.path / ".claude" / "claude.md"

    def generate(self):
        self.template_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.template_path.exists():
            self._create_default_template()
        template = Template(self.template_path.read_text(encoding="utf-8"))
        context = self.db.get_context()
        latest_checkpoint = self.checkpoints.get_latest()
        rendered = template.render(
            project_name=self.path.name,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            git_commit=self.git.get_current_commit()[:8],
            uncommitted=self.git.get_uncommitted_files(),
            checkpoint=latest_checkpoint,
            recent_actions=context["recent_actions"][:10],
            recent_decisions=context["recent_decisions"],
            invariants=context["invariants"],
            stalled_tasks=context["stalled_tasks"]
        )
        self.output_path.write_text(rendered, encoding="utf-8")

    def _create_default_template(self):
        default = """# {{ project_name }}

**Сгенерировано:** {{ generated_at }}
**Git:** {{ git_commit }}

{% if stalled_tasks %}
## ⚠️ Прерванные задачи
{% for task in stalled_tasks %}
- **{{ task.name }}** ({{ task.task_id }})
{% endfor %}
{% endif %}

## 🎯 Последний чекпоинт
{% if checkpoint %}
**{{ checkpoint.summary }}** ({{ checkpoint.timestamp[:19] }})

Следующие шаги:
{% for step in checkpoint.next_steps %}
- [ ] {{ step }}
{% endfor %}
{% else %}
Нет чекпоинтов
{% endif %}

## Ключевые решения
{% if recent_decisions %}
{% for d in recent_decisions %}
**{{ d.category }}:** {{ d.decision }}
> {{ d.question }}
{% endfor %}
{% else %}
Решения не записаны
{% endif %}

## 📝 Последние действия
{% for action in recent_actions %}
- [{{ action.type }}] {{ action.description }} ({{ action.timestamp[:19] }})
{% endfor %}

## 🔑 Устоявшиеся паттерны
{% if invariants %}
{% for inv in invariants %}
- {{ inv.category }}: {{ inv.pattern }} (×{{ inv.count }})
{% endfor %}
{% else %}
Паттерны не накоплены
{% endif %}

## ⚠️ Некоммиченные изменения
{% if uncommitted %}
{% for f in uncommitted %}
- {{ f }}
{% endfor %}
{% else %}
Нет некоммиченных изменений
{% endif %}
"""
        self.template_path.write_text(default, encoding="utf-8")
