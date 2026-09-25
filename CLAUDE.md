@AGENTS.md
@IMPLEMENTATION.md

## Claude Code specifics
- Slash commands: `.claude/commands/`. Skills: `.claude/skills/`. Hooks: `.claude/hooks/`.
- Permissions and hooks: shared ones are committed in `.claude/settings.json` (including the
  `data/` guard of AGENTS.md §5.5); machine-personal ones stay in `.claude/settings.local.json`
  (gitignored).
- Earlier versions of this file are archived at [docs/_bup_CLAUDE.md](docs/_bup_CLAUDE.md).
