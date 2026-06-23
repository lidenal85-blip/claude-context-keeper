#!/bin/bash
# Установка Claude Context Keeper

set -e

echo "🔧 Установка Claude Context Keeper..."
echo ""

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 не найден. Установите Python 3.10+"
    exit 1
fi

echo "✅ Python найден: $(python3 --version)"

# Установка зависимостей
echo "📦 Установка зависимостей..."
pip install -r requirements.txt

# Создание конфигурации MCP
echo "⚙️ Настройка MCP..."
MCP_CONFIG_DIR="$HOME/.config/claude"
mkdir -p "$MCP_CONFIG_DIR"

CURRENT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat > "$MCP_CONFIG_DIR/mcp_config.json" << MCPEOF
{
  "mcpServers": {
    "claude-logger": {
      "command": "python",
      "args": ["$CURRENT_DIR/mcp_server.py"],
      "env": {"PYTHONPATH": "$CURRENT_DIR"}
    }
  }
}
MCPEOF

echo "✅ MCP конфигурация создана: $MCP_CONFIG_DIR/mcp_config.json"

# Копирование глобальных инструкций
if [ -f "templates/root_claude.md" ]; then
    cp templates/root_claude.md "$HOME/claude.md"
    echo "✅ Глобальные инструкции скопированы в ~/claude.md"
fi

echo ""
echo "🎉 Установка завершена!"
echo ""
echo "Дальнейшие шаги:"
echo "1. Перезапустите Claude Code"
echo "2. Для нового проекта: просто начните работу"
echo "3. Для существующего проекта: вызовите migrate_project()"
