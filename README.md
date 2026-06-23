# Claude Context Keeper

MCP-сервер для непрерывной работы Claude Code через сессии и аккаунты.

## Ключевые возможности

- **Буферизованное логирование** — экономия токенов, запись пачками
- **Чекпоинты с привязкой к Git** — каждый снимок знает свой коммит
- **Детектор прерванных задач** — Claude видит незавершённое
- **Атомарный fallback** — при сбое SQLite пишет в pending.jsonl
- **WAL mode с автоочисткой** — конкурентный доступ без блокировок
- **Экспорт промпт-инъекта** — бесшовный переход между аккаунтами

## Быстрый старт

```bash
pip install -r requirements.txt
```

Добавить в ~/.config/claude/mcp_config.json:

```json
{
  "mcpServers": {
    "claude-logger": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"],
      "env": {"PYTHONPATH": "/path/to/claude-context-keeper"}
    }
  }
}
```

