## LeetCode Coach

Creates a personalized, seven-day LeetCode plan: 1–3 solved problems to review and 1–3 unsolved problems to practice each day. Each recommendation includes its LeetCode frontend ID and problem URL.

### Setup

```bash
uv sync --group dev
cp .env.example .env
# Fill in LEETCODE_USERNAME and LLM_API_KEY in .env
uv run leetcode-coach
```

The command writes a dated plan to `data/plans/`.

If your runner has a short execution limit, split the workflow:

```bash
uv run leetcode-coach --sync-only
uv run leetcode-coach --from-cache
```

### Your own model provider

Any provider that offers the OpenAI-compatible Chat Completions API and JSON mode can be used. Set these in `.env`:

```dotenv
LLM_API_KEY=your_provider_key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-id
```

Leave `LLM_BASE_URL` empty to use OpenAI. `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` are accepted as backwards-compatible aliases. The provider must support `POST /chat/completions` and `response_format: {"type": "json_object"}`.

### LeetCode cookies

For public profile data, a username alone may be enough. For an authenticated accepted-problem list, sign in to LeetCode in your browser and copy the `LEETCODE_SESSION` and `csrftoken` cookie values into the local `.env` file. Never commit that file. The app sends them only to `leetcode.com`.

### Weekly scheduling

Use the included application command in a weekly scheduler, for example:

```cron
0 9 * * 1 cd /absolute/path/to/leetcode-coach && /path/to/uv run leetcode-coach
```

The project is also configured with a Codex weekly task when created through the desktop app.
