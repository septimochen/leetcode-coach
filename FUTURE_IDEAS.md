# LeetCode Coach — Future Ideas

## Next: learn from plan completion

- [ ] Store each generated plan as structured JSON alongside its Markdown rendering.
- [ ] At the next sync, compare planned practice titles with newly accepted submissions.
- [ ] Add a weekly completion summary: completed, skipped, and still pending.
- [ ] Tell the planner about completion patterns, but preserve the full solved-title exclusion list.
- [ ] Decide an explicit carry-over policy for unfinished practice, rather than silently repeating it.

## Study-plan quality

- [ ] Add a weekly time budget and a per-session duration estimate.
- [ ] Support modes such as maintain, interview sprint, topic repair, and hard-problem ramp-up.
- [ ] Prefer spaced review based on when a learner solved a problem, once submission timing is available.
- [ ] Add an end-of-week reflection prompt and include its answer in the following plan.
- [ ] Summarize topic and difficulty balance in the generated plan.

## Everyday access

- [ ] Add `leetcode-coach today` to print the current day's review and practice links.
- [ ] Add `leetcode-coach status` for the latest cache and plan summary.
- [ ] Add `leetcode-coach history` to browse prior plans and completion metrics.
- [ ] Generate a private, local static dashboard from stored plans and progress data.

## Optional frontend (after the workflow proves useful)

- [ ] Define whether the frontend is local-only, authenticated, or a static private deployment.
- [ ] Build the frontend from the same saved structured-plan data; do not make it the only plan source.
- [ ] Display weekly plans, topic/difficulty trends, and completion history.
- [ ] Avoid exposing LeetCode session cookies, model keys, or private progress in client-side code.
