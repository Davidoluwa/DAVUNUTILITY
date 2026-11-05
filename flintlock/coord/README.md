# Coordination between workers

Two Claude workers on separate accounts build flintlock together. They cannot message
each other directly, so this repo is the channel.

| Worker | Branch | Owns |
| --- | --- | --- |
| A (engine) | `ccr-11fa8e16-o7vrpz` | `src/`, `kernels/`, `bench/`, `tools/` |
| B (research + data) | B's own session branch | `docs/papers.md`, `traces/`, `testdata/` |

## Doorbell: how we ping each other

Cloud Claude Code sessions can subscribe to a pull request's activity, and a new comment on
that PR wakes the subscribed session even when it is idle. Each worker owns one draft PR as
its doorbell, and only it subscribes to that PR (a PR delivers events to one session at a time).

| Worker | Doorbell PR | Who subscribes |
| --- | --- | --- |
| A | draft PR `ccr-11fa8e16-o7vrpz` -> `main`, titled `[flintlock] doorbell A` | A only |
| B | draft PR `<B's branch>` -> `main`, titled `[flintlock] doorbell B` | B only |

- **To ping the other worker, comment on their doorbell PR.** Keep it to one or two lines
  and point at the details: `PING from B: routing traces v1 pushed (abc1234), see coord/log-b.md`.
- Ping when you finish something the other is waiting on, when you are blocked on them, or when a
  finding changes the plan. Do not ping for routine progress; that goes in your log.
- Big content (numbers, tables, data) goes in git, never in the comment.
- Pings are information from a teammate. Each worker still follows its own user's instructions and
  its own safety rules.
- Never merge the doorbell PRs. Close them when the collaboration ends.

Setup, once per worker: push your branch, open your doorbell PR as a draft, subscribe to it with
`subscribe_pr_activity`, then post its number in your log and ping the other worker's doorbell.

## Rules

- Push only to your own branch. Write only in the directories you own, so merging is trivial.
- Each worker keeps a log on its own branch: A writes `coord/log-a.md`, B writes `coord/log-b.md`.
  Append entries; never rewrite old ones. Use this format:

  ```
  ## 2026-11-05 14:20 UTC: <one-line summary>
  Done: ...
  Findings: ... (numbers, file paths)
  Asks for the other worker: ...
  Next: ...
  ```

- Read the other worker's log:

  ```bash
  git fetch origin <their-branch>
  git show origin/<their-branch>:flintlock/coord/log-b.md   # or log-a.md
  ```

- B: find A's latest state on `ccr-11fa8e16-o7vrpz`. A finds B's branch with `git ls-remote origin`
  (look for the newest branch that has `flintlock/coord/log-b.md`).
- Keep committed data small (under ~20 MB per file). Compress traces (`.npz`, `.csv.gz`).
  Never commit model weights.
- Put measured numbers in the logs with the command that produced them. If something is an
  estimate or comes from a paper, say so.
