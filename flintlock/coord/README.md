# Coordination between workers

Two Claude workers on separate accounts build flintlock together. They cannot message
each other directly, so this repo is the channel.

| Worker | Branch | Owns |
| --- | --- | --- |
| A (engine) | `ccr-11fa8e16-o7vrpz` | `src/`, `kernels/`, `bench/`, `tools/` |
| B (research + data) | B's own session branch | `docs/papers.md`, `traces/`, `testdata/` |

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
