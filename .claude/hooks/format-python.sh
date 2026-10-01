#!/usr/bin/env bash
# PostToolUse hook (Write|Edit): formats the Python file Claude just wrote or
# edited the same way `make format` does - black, then `ruff check --fix`.
# Both tools only exist inside the "web" container (which bind-mounts the repo),
# so this quietly does nothing when the container is not running (or the file
# is not project Python code).

root="${CLAUDE_PROJECT_DIR:-$PWD}"
fp=$(jq -r '.tool_input.file_path // empty')

case "$fp" in
    "$root"/frontend/.web/* | "$root"/.venv/*) exit 0 ;;
    "$root"/*.py) ;;
    *) exit 0 ;;
esac

[ -f "$fp" ] || exit 0
cd "$root" || exit 0
docker compose ps --status running --services 2>/dev/null | grep -qx web || exit 0

rel="${fp#"$root"/}"
docker compose exec -T web black -q "$rel" > /dev/null 2>&1
docker compose exec -T web ruff check --fix -q "$rel" > /dev/null 2>&1
exit 0
