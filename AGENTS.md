# LeetCode Coach contributor guide

## Project overview

This is a Python CLI that:

1. Fetches a signed-in learner's accepted LeetCode progress with `userProgressQuestionList`.
2. Caches solved problems in `data/progress.json`.
3. Sends 80% of solved-history context plus the complete solved-title exclusion list to an OpenAI-compatible model.
4. Writes an Obsidian-compatible Markdown checklist to `data/plans/YYYY-MM-DD.md`.

## Working conventions

- Use `uv` for all project commands. Run `uv run ruff check .` and `uv run pytest` after code changes.
- Keep code formatted and typed consistently with the existing Python style.
- Use `rg` for codebase searches.
- Make file changes with `apply_patch`.
- Do not overwrite user-generated files in `data/` unless the requested workflow explicitly generates or updates them.

## LeetCode integration

- The progress query is authenticated through `LEETCODE_SESSION` and optionally `csrftoken`.
- `userProgressQuestionList` represents user progress, not the global LeetCode catalog. Do not label it as a catalog or derive an unsolved list from it.
- The API may return difficulty values in uppercase (for example, `HARD`); compare difficulty values case-insensitively.
- Keep the request filter explicit: `{"skip": 0, "limit": 300}`.
- Never log cookie, CSRF-token, or API-key values. The logging module provides redaction helpers.

## Plan-generation contract

- Do not request JSON mode or parse model output as a Pydantic plan.
- Request Markdown only, with Obsidian tasks such as `- [ ] Review: [Title](URL)` and `- [ ] Practice: [Title](URL)`.
- Reviews must come from the supplied solved history.
- Practice problems are selected by the model, but it must receive the complete solved-title exclusion list and must not repeat a practice problem within a week.
- Preserve the dated `.md` output convention in `data/plans/`.

## Tests

- Update tests whenever changing a GraphQL response field, cache shape, prompt contract, or output extension.
- Keep tests network-free by stubbing `httpx.post` and `OpenAI` calls.
