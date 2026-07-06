# CLAUDE.md

The shared, vendor-neutral collaboration rules for AI coding tools live in [AGENTS.md](AGENTS.md) (also read by Codex, Cursor, etc.). Claude Code reads *this* file, so the import below pulls in the shared rules — one source of truth for every tool.

@AGENTS.md

## Claude Code specifics
- Slash commands: `.claude/commands/` (`commit-git`, `create-prd`, `documentation-update`). Skills: `.claude/skills/`.
- Permissions/config: shared safe allows are committed in `.claude/settings.json`; machine-personal ones stay in `.claude/settings.local.json` (gitignored).
- The pre-AGENTS.md original of this file is archived at [docs/_bup_CLAUDE.md](docs/_bup_CLAUDE.md).
