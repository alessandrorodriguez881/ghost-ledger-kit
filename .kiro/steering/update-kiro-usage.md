---
inclusion: manual
---

# Update the "How we used Kiro" section

Use this file from chat with `#update-kiro-usage`. It carries the same instructions as the manual `kiro-usage` hook, for Kiro versions that do not offer manual hooks.

Rewrite the "How we used Kiro" section of `README.md` as a Markdown table with the columns: Kiro feature | What we did | Why it mattered. Rows, in this order: specs, steering, hooks, MCP, property-based testing, powers. If `README.md` does not exist yet, tell the developer and stop; do not create it. Replace only that section and leave the rest of the README untouched.

Ground every cell in evidence. Before writing, list `.kiro/` (specs, steering, hooks, agents, settings) and the tests, and cite the real file names in the "What we did" column:

- specs: `.kiro/specs/*/` (requirements, design, tasks)
- steering: `.kiro/steering/*.md`, including the always-included rules and the manual `update-kiro-usage.md`
- hooks: `.kiro/hooks/*.kiro.hook`
- property-based testing: the Hypothesis tests (`max_examples=200`, the `loaded_source_refs` no-invention property) in `tests/` and `apps/*/tests/`
- MCP and powers: check for `.kiro/settings/mcp.json` and for installed powers; if there is no evidence of use, write "Not used" in the row and say why it was not needed

Never invent a feature, file, number or result we did not use. Do not state test counts or coverage unless you ran the tests or read them from a fresh report. In "Why it mattered", tie each row to the project's promise that no figure is invented and every figure traces to a source row.

After editing, report what you checked, which rows are "Not used", and any gap.
