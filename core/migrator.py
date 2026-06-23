"""Мигратор существующих проектов в систему Claude Context Keeper.

Сканирует проект, анализирует структуру и git-историю,
создаёт начальную инфраструктуру и первый чекпоинт.
"""

import json
from datetime import datetime
from pathlib import Path

from core.db import StateDB
from core.git_context import GitContext
from core.checkpoints import CheckpointManager
from core.context_generator import ContextGenerator


class ProjectMigrator:
    def __init__(self, project_path: Path):
        self.path = Path(project_path)
        self.db = StateDB(self.path)
        self.git = GitContext(self.path)
        self.checkpoints = CheckpointManager(self.path)
        self.generator = ContextGenerator(
            self.path, self.db, self.git, self.checkpoints
        )

    def migrate(self) -> dict:
        """Мигрирует существующий проект в новую систему."""
        result = {
            "project": str(self.path),
            "steps": [],
            "warnings": []
        }

        # Шаг 1: Проверка существующей структуры
        result["steps"].append(self._check_existing())

        # Шаг 2: Анализ проекта
        analysis = self._analyze_project()
        result["analysis"] = analysis

        # Шаг 3: Создание инфраструктуры
        result["steps"].append(self._create_infrastructure())

        # Шаг 4: Импорт git-истории
        if self.git.is_git_repo():
            result["steps"].append(self._import_git_history())

        # Шаг 5: Создание начального чекпоинта
        result["steps"].append(self._create_initial_checkpoint(analysis))

        # Шаг 6: Генерация claude.md
        self.generator.generate()
        result["steps"].append("claude.md сгенерирован")

        return result

    def _check_existing(self) -> str:
        """Проверяет, не мигрирован ли проект ранее."""
        claude_dir = self.path / ".claude"
        if claude_dir.exists():
            return "⚠️ Проект уже содержит .claude/ — миграция пропущена"
        return "✅ Проект не мигрирован — продолжаем"

    def _analyze_project(self) -> dict:
        """Анализирует структуру существующего проекта."""
        analysis = {
            "detected_stack": [],
            "file_count": 0,
            "dir_count": 0,
            "top_dirs": [],
            "has_git": self.git.is_git_repo(),
            "last_commit": None,
            "total_commits": 0,
            "key_files": []
        }

        # Определяем стек по файлам
        stack_indicators = {
            "requirements.txt": "Python",
            "Pipfile": "Python",
            "pyproject.toml": "Python",
            "setup.py": "Python",
            "package.json": "Node.js",
            "tsconfig.json": "TypeScript",
            "Cargo.toml": "Rust",
            "go.mod": "Go",
            "Gemfile": "Ruby",
            "composer.json": "PHP",
            "Dockerfile": "Docker",
            "docker-compose.yml": "Docker Compose",
            "Makefile": "Make"
        }

        key_files_indicators = {
            "app/": "FastAPI/Flask приложение",
            "src/": "Исходный код",
            "tests/": "Тесты",
            "migrations/": "Миграции БД",
            "docs/": "Документация",
            "config/": "Конфигурация",
            "api/": "API слой",
            "models/": "Модели данных",
            "services/": "Бизнес-логика"
        }

        # Сканируем корень проекта
        for item in self.path.iterdir():
            if item.is_file():
                analysis["file_count"] += 1
                if item.name in stack_indicators:
                    analysis["detected_stack"].append(
                        stack_indicators[item.name]
                    )
                if item.name in [".gitignore", "README.md", "LICENSE",
                                "CHANGELOG.md", "docker-compose.yml"]:
                    analysis["key_files"].append(str(item.name))
            elif item.is_dir() and not item.name.startswith('.'):
                analysis["dir_count"] += 1
                analysis["top_dirs"].append(str(item.name))
                if item.name in key_files_indicators:
                    analysis["key_files"].append(
                        f"{item.name}/ ({key_files_indicators[item.name]})"
                    )

        # Git-анализ
        if self.git.is_git_repo():
            analysis["last_commit"] = self.git.get_current_commit()[:8]
            try:
                import subprocess
                result = subprocess.run(
                    ["git", "rev-list", "--count", "HEAD"],
                    cwd=self.path, capture_output=True, text=True
                )
                if result.returncode == 0:
                    analysis["total_commits"] = int(result.stdout.strip())
            except Exception:
                pass

        # Определяем основной язык
        if not analysis["detected_stack"]:
            # Пробуем угадать по расширениям файлов
            extensions = {}
            for f in self.path.rglob("*"):
                if f.is_file() and f.suffix:
                    ext = f.suffix.lower()
                    extensions[ext] = extensions.get(ext, 0) + 1

            ext_to_lang = {
                ".py": "Python",
                ".js": "JavaScript",
                ".ts": "TypeScript",
                ".rs": "Rust",
                ".go": "Go",
                ".rb": "Ruby",
                ".php": "PHP",
                ".java": "Java",
                ".kt": "Kotlin"
            }

            for ext, count in sorted(extensions.items(),
                                    key=lambda x: x[1], reverse=True):
                if ext in ext_to_lang:
                    analysis["detected_stack"].append(ext_to_lang[ext])
                    break

        return analysis

    def _create_infrastructure(self) -> str:
        """Создаёт структуру директорий для системы."""
        dirs_to_create = [
            self.path / ".claude",
            self.path / "logs",
            self.path / "checkpoints"
        ]
        for d in dirs_to_create:
            d.mkdir(parents=True, exist_ok=True)
        return "✅ Инфраструктура создана (.claude/, logs/, checkpoints/)"

    def _import_git_history(self) -> str:
        """Импортирует ключевые моменты из git-истории."""
        try:
            import subprocess
            # Получаем последние 10 значимых коммитов
            result = subprocess.run(
                ["git", "log", "--oneline", "-10", "--no-merges"],
                cwd=self.path, capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                commits = result.stdout.strip().split('\n')
                # Регистрируем как задачу импорта
                task_id = f"import_{int(datetime.now().timestamp())}"
                self.db.register_task(task_id, "Импорт git-истории")

                for commit in commits[:5]:
                    self.db.log_action(
                        task_id, "historical_commit",
                        commit.strip(),
                        {"source": "git_history"}
                    )

                self.db.complete_task(
                    task_id,
                    f"Импортировано {len(commits)} коммитов из истории",
                    []
                )
                return f"✅ Импортировано {len(commits)} коммитов из git-истории"
        except Exception:
            pass
        return "⚠️ Git-история не импортирована"

    def _create_initial_checkpoint(self, analysis: dict) -> str:
        """Создаёт начальный чекпоинт на основе анализа."""
        stack_str = ", ".join(analysis["detected_stack"]) or "не определён"

        summary = (
            f"Миграция существующего проекта в Claude Context Keeper. "
            f"Стек: {stack_str}. "
            f"Файлов: {analysis['file_count']}, "
            f"директорий: {analysis['dir_count']}"
        )

        next_steps = [
            "Ознакомиться со структурой проекта через claude.md",
            "Проверить корректность определённого стека",
            "Начать работу с создания новой задачи через start_task"
        ]

        context = {
            "migration": True,
            "migrated_at": datetime.now().isoformat(),
            "analysis": analysis,
            "existing_structure": {
                "top_dirs": analysis["top_dirs"],
                "key_files": analysis["key_files"]
            }
        }

        checkpoint = self.checkpoints.create(
            summary=summary,
            next_steps=next_steps,
            context=context,
            git_commit=self.git.get_current_commit()
        )

        return f"✅ Начальный чекпоинт создан: {checkpoint['id']}"
