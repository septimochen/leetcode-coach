## LeetCode Coach

Creates a personalized, seven-day LeetCode plan: 1–3 solved problems to review and 1–3 unsolved problems to practice each day. Each recommendation includes its LeetCode frontend ID and problem URL.

### Setup

```bash
uv sync --group dev
cp .env.example .env
# Fill in LEETCODE_USERNAME and LLM_API_KEY in .env
uv run leetcode-coach
```

The command writes a dated Obsidian-compatible Markdown checklist to `data/plans/`.

### Cloud deployment with GitHub Actions

The repository includes [a GitHub Actions workflow](.github/workflows/weekly-plan.yml)
that runs every Monday at 09:00 Asia/Shanghai (01:00 UTC). It keeps the normal Python
CLI, stores the generated Markdown temporarily on the GitHub Actions runner, and
uploads it as a private workflow artifact, and emails the same Markdown file as an
attachment. No object-storage subscription is required.

Add these as encrypted repository secrets in GitHub, along with the existing LeetCode
and model-provider secrets:

```text
LEETCODE_USERNAME
LEETCODE_SESSION
LEETCODE_CSRF_TOKEN
LLM_API_KEY
LLM_BASE_URL       # optional
LLM_MODEL          # optional
EMAIL_TO
SMTP_USERNAME
SMTP_PASSWORD       # Gmail App Password, not your normal password
```

The workflow sets `STORAGE_BACKEND=local` and `OUTPUT_DIR=data/plans`. The runner's
temporary files are discarded after the job; the uploaded artifact is retained for 90
days. Each weekly run fetches fresh LeetCode progress, so a persistent cache is not
required.

The workflow uses Gmail SMTP on `smtp.gmail.com:465` with SSL. Enable 2-Step
Verification, create a Gmail App Password, and store it as `SMTP_PASSWORD`. The
sender address is `SMTP_USERNAME`. Email delivery is disabled for local runs unless
`EMAIL_ENABLED=true` is configured.

For local development, leave `STORAGE_BACKEND=local` (the default). The same CLI then
continues to write to the local `data/` directory.

Run the workflow manually from the repository's Actions tab with
`Generate weekly LeetCode plan` > `Run workflow`. Open the completed run and download
the `leetcode-plan-<run-id>` artifact.

If your runner has a short execution limit, split the workflow:

```bash
uv run leetcode-coach --sync-only
uv run leetcode-coach --from-cache
```

### Your own model provider

Any provider that offers the OpenAI-compatible Chat Completions API and structured JSON/tool output can be used. The model response is validated as a typed weekly plan and then rendered to Obsidian Markdown. Set these in `.env`:

```dotenv
LLM_API_KEY=your_provider_key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-id
```

Leave `LLM_BASE_URL` empty to use OpenAI. `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` are accepted as backwards-compatible aliases. The provider must support `POST /chat/completions`.

### LeetCode cookies

For public profile data, a username alone may be enough. For an authenticated accepted-problem list, sign in to LeetCode in your browser and copy the `LEETCODE_SESSION` and `csrftoken` cookie values into the local `.env` file. Never commit that file. The app sends them only to `leetcode.com`.

### Logging

Diagnostics go to stderr in text format, one line per event, so stdout still contains only the result line the command has always printed:

```text
2026-09-11 09:00:04+0800 INFO     leetcode_coach: leetcode-coach starting (username=ada, model=gpt-5-mini, provider=OpenAI)
2026-09-11 09:00:04+0800 INFO     leetcode_coach.leetcode: leetcode.progress: started {'username': 'ada'}
2026-09-11 09:01:11+0800 INFO     leetcode_coach.leetcode: leetcode.progress: completed in 67.02s {'solved': 143}
2026-09-11 09:02:40+0800 INFO     leetcode_coach.coach: llm.structured_plan: completed in 88.40s {'total_tokens': 6211}
```

Choose the verbosity with `--log-level`, `LOG_LEVEL` in `.env`, or `LEETCODE_COACH_LOG_LEVEL` (highest priority wins for the flag):

```bash
uv run leetcode-coach --log-level DEBUG   # adds each LeetCode request/response and prompt size
uv run leetcode-coach --log-file logs/coach.log
```

`DEBUG` additionally enables `httpx2`, `httpcore`, and `openai` request logs. Any failure is recorded once with a traceback before the process exits (`2` for missing settings, `1` for everything else).

Credentials are kept in Pydantic `SecretStr` settings and are not included in the application's normal log messages. Avoid logging raw settings or exception messages that contain credential values.

### Weekly scheduling

Use the included application command in a weekly scheduler, for example:

```cron
0 9 * * 1 cd /absolute/path/to/leetcode-coach && /path/to/uv run leetcode-coach --log-file logs/leetcode-coach.log
```
