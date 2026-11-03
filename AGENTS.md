# LeetCode Coach contributor guide

## Project overview

This is a Python CLI that:

1. Reads accepted LeetCode history from an authenticated Streamable HTTP MCP server.
2. Caches solved problems in `data/progress.json`.
3. Sends the full solved-history context plus the complete solved-title exclusion list to an OpenAI-compatible model through PydanticAI.
4. Validates the model response as a `WeeklyPlan` and renders it to an Obsidian-compatible Markdown checklist in `data/plans/YYYY-MM-DD.md`.

## Working conventions

- Use `uv` for all project commands. The root `Makefile` provides `make sync`, `make build`, `make format`, `make format-check`, `make check`, and individual `make lint`, `make typecheck`, and `make test` targets.
- Run `make check` after code changes; it runs Ruff lint, ty, and pytest. Run `make format` when Python formatting needs updating, then use `make format-check` to verify it.
- Keep code formatted and typed consistently with the existing Python style.
- Use `rg` for codebase searches.
- Make file changes with `apply_patch`.
- Do not overwrite user-generated files in `data/` unless the requested workflow explicitly generates or updates them.
- After completing each task, commit the task's changes with a descriptive message and push the commit to the current branch. Do not include unrelated user changes in the commit.

## MCP history integration

- Configure `MCP_URL` and `MCP_AUTH_TOKEN`; use Streamable HTTP with bearer authentication.
- Call `list_ac_submissions` with `limit: 100` and follow `nextCursor` until null.
- The tool supplies `title`, `titleSlug`, and Unix-second `timestamp`, not IDs, difficulty, or topics. Preserve missing metadata as unknown and retain the latest record per slug.
- This reads stored history; it does not refresh LeetCode or expose the global catalog. Collection may have gaps or approximate timestamps; do not infer solve frequency.
- Never log bearer tokens, API keys, raw history payloads, or transport exception details.

## Plan-generation contract

- Use PydanticAI with the OpenAI-compatible Chat Completions transport and `WeeklyPlan` as the structured output type. Do not use the Responses API for the AMD provider.
- Keep automatic PydanticAI retries disabled unless the workflow explicitly changes; latency matters for the AMD endpoint.
- Do not use native JSON Schema output for `DeepSeek-V4-Flash`; AMD rejects that mode. Tool-based structured output is supported.
- Convert the validated `WeeklyPlan` to Markdown in the renderer. Markdown formatting should not be requested as the model's primary output.
- Reviews must come from the supplied solved history. Preserve exact titles and URLs; infer numeric IDs only when history metadata does not provide them.
- Practice problems are selected by the model, but it must receive the complete solved-title exclusion list and should not repeat a practice problem within a week.
- Semantic plan issues such as a solved practice recommendation are warnings, not fatal errors; Pydantic field/schema validation remains enforced.
- Preserve the dated `.md` output convention in `data/plans/`.

## Model-provider compatibility

- The configured AMD Radeon Cloud public endpoint supports Chat Completions, tool calling, and JSON object output, but not the Responses API or native JSON Schema output for the configured vision model.
- AMD may return malformed optional routing metadata in Chat Completions responses. The compatibility model discards that metadata before PydanticAI validation; preserve this workaround unless the provider response contract changes.
- Do not log API keys, cookies, prompts containing private data, or raw provider responses.

## Tests

- Update tests whenever changing an MCP result field, cache shape, prompt contract, or output extension.
- Keep tests network-free by stubbing the MCP client/transport and the PydanticAI `Agent`/provider construction. Use `httpx2.MockTransport` for SDK integration tests.
