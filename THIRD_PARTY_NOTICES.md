# Third-party notices

## andrej-karpathy-skills

- Used in: AGENTS.md, preamble and §1–4 (verbatim).
- Source: https://github.com/forrestchang/andrej-karpathy-skills (`CLAUDE.md`)
- License: MIT, as stated in the upstream README. The upstream repository ships no LICENSE file, so
  the standard MIT terms are reproduced below.

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
> associated documentation files (the "Software"), to deal in the Software without restriction,
> including without limitation the rights to use, copy, modify, merge, publish, distribute,
> sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or
> substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
> NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
> NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES
> OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
> CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## frontend-design (Claude Code skill)

- Used in: `.claude/skills/frontend-design/SKILL.md` (verbatim).
- Source: https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md, identical to
  https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md
  (claude-code commit `dec92bc87ab6fe9c7be0fcba1f97966f902dd243`, 2026-09-28).
- License: Apache-2.0, copyright Anthropic PBC; full text at `.claude/skills/frontend-design/LICENSE.txt`.

## ui-ux-pro-max (Claude Code skill)

- Used in: `.claude/skills/ui-ux-pro-max/` (SKILL.md, references, scripts, data).
- Source: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill, directory
  `.claude/skills/ui-ux-pro-max/` at commit `09170eec67eefd46a7ae85de61b40c194020f997` (v2.13.0,
  2026-09-27).
- License: MIT, copyright (c) 2024 Next Level Builder; full text at
  `.claude/skills/ui-ux-pro-max/LICENSE`.
- Modifications: in SKILL.md, `${CLAUDE_PLUGIN_ROOT}` is replaced by `$(git rev-parse --show-toplevel)`
  (installed as a project skill, not a plugin); the upstream developer tests `scripts/tests/` are
  left out. Everything else is verbatim.
