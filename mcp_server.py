#!/usr/bin/env python3
"""MCP-сервер Claude Context Keeper — командный режим."""

import asyncio
import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from core.db import StateDB
from core.buffer import BufferedLogger
from core.checkpoints import CheckpointManager
from core.git_context import GitContext
from core.context_generator import ContextGenerator
from core.prompt_export import PromptExporter
from core.migrator import ProjectMigrator

app = Server("claude-context-keeper")
projects = {}


def get_project(project_path: str) -> dict:
    path = Path(project_path)
    if project_path not in projects:
        db = StateDB(path)
        git = GitContext(path)
        checkpoints = CheckpointManager(path)
        projects[project_path] = {
            "db": db,
            "logger": BufferedLogger(db),
            "checkpoints": checkpoints,
            "git": git,
            "generator": ContextGenerator(path, db, git, checkpoints),
            "exporter": PromptExporter(path, db, git, checkpoints),
            "migrator": ProjectMigrator(path)
        }
    return projects[project_path]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="migrate_project",
             description="Мигрирует существующий проект в систему Claude Context Keeper.",
             inputSchema={
                 "type": "object",
                 "properties": {
                     "project_path": {"type": "string"}
                 },
                 "required": ["project_path"]
             }),
        Tool(name="start_task",
             description="Начать новую задачу. Указывай developer!",
             inputSchema={
                 "type": "object",
                 "properties": {
                     "project_path": {"type": "string"},
                     "task_name": {"type": "string"},
                     "developer": {"type": "string", "description": "Имя разработчика (alice, bob, lead-dev)"}
                 },
                 "required": ["project_path", "task_name"]
             }),
        Tool(name="log",
             description="Записать действие (буферизуется).",
             inputSchema={
                 "type": "object",
                 "properties": {
                     "project_path": {"type": "string"},
                     "action_type": {
                         "type": "string",
                         "enum": ["file_created", "file_modified",
                                  "command_executed", "task_progress",
                                  "issue_found", "issue_resolved", "handoff"]
                     },
                     "description": {"type": "string"},
                     "details": {"type": "object"}
                 },
                 "required": ["project_path", "action_type", "description"]
             }),
        Tool(name="log_decision",
             description="Записать архитектурное решение.",
             inputSchema={
                 "type": "object",
                 "properties": {
                     "project_path": {"type": "string"},
                     "category": {"type": "string"},
                     "question": {"type": "string"},
                     "decision": {"type": "string"},
                     "reasoning": {"type": "string"}
                 },
                 "required": ["project_path", "category", "question", "decision"]
             }),
        Tool(name="complete_task",
             description="Завершить задачу и создать чекпоинт.",
             inputSchema={
                 "type": "object",
                 "properties": {
                     "project_path": {"type": "string"},
                     "summary": {"type": "string"},
                     "next_steps": {"type": "array", "items": {"type": "string"}},
                     "developer": {"type": "string"}
                 },
                 "required": ["project_path", "summary"]
             }),
        Tool(name="restore_context",
             description="Восстановить контекст в начале сессии. Показывает, кто последний работал.",
             inputSchema={
                 "type": "object",
                 "properties": {"project_path": {"type": "string"}},
                 "required": ["project_path"]
             }),
        Tool(name="regenerate_claude_md",
             description="Перегенерировать .claude/claude.md",
             inputSchema={
                 "type": "object",
                 "properties": {"project_path": {"type": "string"}},
                 "required": ["project_path"]
             })
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    proj = get_project(arguments["project_path"])

    if name == "migrate_project":
        result = proj["migrator"].migrate()
        return [TextContent(type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "start_task":
        developer = arguments.get("developer", "unknown")
        task_name = arguments["task_name"]
        full_name = f"[{developer}] {task_name}"
        task_id = proj["logger"].start_task(full_name)
        return [TextContent(type="text",
                text=json.dumps({"task_id": task_id, "developer": developer, "status": "started"}))]

    elif name == "log":
        proj["logger"].log(arguments["action_type"],
                          arguments["description"],
                          arguments.get("details"))
        return [TextContent(type="text",
                text=json.dumps({"status": "buffered"}))]

    elif name == "log_decision":
        proj["logger"].log_decision(
            arguments["category"], arguments["question"],
            arguments["decision"], arguments.get("reasoning"))
        return [TextContent(type="text",
                text=json.dumps({"status": "logged"}))]

    elif name == "complete_task":
        developer = arguments.get("developer", "unknown")
        summary = f"[{developer}] {arguments['summary']}"
        task_id = proj["logger"].complete_task(
            summary, arguments.get("next_steps", []))
        context = proj["db"].get_context()
        proj["git"].create_snapshot(f"checkpoint: {summary[:50]}")
        checkpoint = proj["checkpoints"].create(
            summary,
            arguments.get("next_steps", []),
            context,
            proj["git"].get_current_commit()
        )
        proj["generator"].generate()
        return [TextContent(type="text",
                text=json.dumps({"status": "completed", "task_id": task_id,
                                 "checkpoint": checkpoint["id"], "developer": developer},
                                ensure_ascii=False))]

    elif name == "restore_context":
        recovered = proj["db"].recover_wal()
        stalled = proj["db"].detect_stalled_tasks()
        for task in stalled:
            proj["db"].mark_stalled(task["task_id"])
        proj["generator"].generate()
        latest = proj["checkpoints"].get_latest()

        # Определяем, кто последний работал
        last_developer = "неизвестно"
        if latest and "summary" in latest:
            summary = latest["summary"]
            if summary.startswith("["):
                last_developer = summary[1:].split("]")[0]

        result = {
            "recovered_actions": recovered,
            "stalled_tasks": len(stalled),
            "stalled_list": [t["name"] for t in stalled],
            "latest_checkpoint": latest["summary"] if latest else None,
            "last_developer": last_developer,
            "last_activity": latest["timestamp"][:19] if latest else None
        }
        return [TextContent(type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "regenerate_claude_md":
        proj["generator"].generate()
        return [TextContent(type="text",
                text=json.dumps({"status": "regenerated"}))]

    return [TextContent(type="text",
            text=json.dumps({"error": "unknown tool"}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream)


if __name__ == "__main__":
    asyncio.run(main())
