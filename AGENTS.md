# LeetCode Coach contributor guide

## Project overview

This is a Python CLI that:

1. Fetches a signed-in learner's accepted LeetCode progress with `userProgressQuestionList`.
2. Caches solved problems in `data/progress.json`.
3. Sends 80% of solved-history context plus the complete solved-title exclusion list to an OpenAI-compatible model through PydanticAI.
4. Validates the model response as a `WeeklyPlan` and renders it to an Obsidian-compatible Markdown checklist in `data/plans/YYYY-MM-DD.md`.

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

- Use PydanticAI with the OpenAI-compatible Chat Completions transport and `WeeklyPlan` as the structured output type. Do not use the Responses API for the AMD provider.
- Keep automatic PydanticAI retries disabled unless the workflow explicitly changes; latency matters for the AMD endpoint.
- Do not use native JSON Schema output for `DeepSeek-V4-Flash`; AMD rejects that mode. Tool-based structured output is supported.
- Convert the validated `WeeklyPlan` to Markdown in the renderer. Markdown formatting should not be requested as the model's primary output.
- Reviews must come from the supplied solved history.
- Practice problems are selected by the model, but it must receive the complete solved-title exclusion list and should not repeat a practice problem within a week.
- Semantic plan issues such as a solved practice recommendation are warnings, not fatal errors; Pydantic field/schema validation remains enforced.
- Preserve the dated `.md` output convention in `data/plans/`.

## Model-provider compatibility

- The configured AMD Radeon Cloud public endpoint supports Chat Completions, tool calling, and JSON object output, but not the Responses API or native JSON Schema output for the configured vision model.
- AMD may return malformed optional routing metadata in Chat Completions responses. The compatibility model discards that metadata before PydanticAI validation; preserve this workaround unless the provider response contract changes.
- Do not log API keys, cookies, prompts containing private data, or raw provider responses.

## Tests

- Update tests whenever changing a GraphQL response field, cache shape, prompt contract, or output extension.
- Keep tests network-free by stubbing `httpx2.post` and the PydanticAI `Agent`/provider construction.
