# Synod architecture

This is the detailed version: what every piece believes, how each decision is computed, and why.

## 1. Design rules

1. **No node sees the answer or the task family.** Nodes get a `TaskView` (history, tolerance, system pressure). Labels arrive after delivery, for 35% of tasks.
2. **The council has no opinions.** It runs a fixed meeting protocol. Every judgement comes from a node's learned beliefs.
3. **One objective for everyone.** `U = +1 correct, −1 wrong, 0 abstain, −λ·compute` with λ = 0.02. A node's decisions are judged by their effect on `U`, not on its own score.
4. **Nobody is certain.** Beliefs are capped at 0.99, so evidence can always move them.

## 2. Beliefs (`beliefs.py`)

### Competence: P(success | situation)

A hierarchical Beta-Bernoulli model over tuple keys. Every prefix of a key is its own cell, and a cell's prior is its parent's posterior mean with pseudo-count `s`:

```
m_0 = prior
m_k = (a_k + s·m_{k-1}) / (a_k + b_k + s)      for each prefix k of the key
```

Sparse situations borrow from broader ones and specialise as evidence arrives. Counts decay on update (γ ≈ 0.995), so beliefs follow a changing world. A node keeps several of these:

| model | key | question |
|---|---|---|
| `competence` | `("ctx", *sig)` / `("g", *glance_evidence, *sig)` / `("p", *proposal_evidence, *sig)` | how often am I right here, given what I saw? |
| `usefulness` | `sig` | how often does looking here end in a worthwhile bid? |
| `review_tnr`, `review_tpr` | `(reviewer, *sig)` | P(endorse \| lead right), P(reject \| lead wrong) for each reviewer |
| `review_answers` | `(reviewer, *sig)` | how often does that reviewer give a verdict at all? |
| `dissent` | `(reviewer, *counter_evidence, *sig)` | when that reviewer counter-proposes, how often is it right? |

`sig` is a coarse, shared description of the task's shape: precision (tight/loose), integer/real, smooth/rough, growth (decaying/steady/explosive). See `perception.py`.

Because confidence comes from `competence[("p", evidence, sig)]`, raw scores (ensemble spread, residual fits, memory distance) only pick a bucket. The calibrated probability is learned from outcomes. This is histogram-binning calibration, made contextual.

### ClaimCalibrator: trust

Each node keeps its own map of each peer's claims, binned by stated confidence:

```
adjust(peer, c) = (hits_bin + s·c) / (n_bin + s)          (s = 4, decay 0.9)
```

With no evidence a claim is taken at face value. A calibrated peer is believed exactly. A peer whose 97% claims keep failing gets discounted within a handful of outcomes. The council's reading of any claim is the **median of the other nodes' maps**, so no node grades itself.

### DriftMonitor

A one-sided CUSUM on `confidence − outcome − slack`. A calibrated node drifts to zero; a node that's suddenly worse than it believes crosses the threshold in a few labeled outcomes.

## 3. The meeting (`council.py`)

### 3.1 Open-outcry bidding

Nodes are asked in order of how cheap their glance is. Each node:

1. **Covered?** If the best bid already on the table has belief `b`, and even a perfect answer from me couldn't pay for my look:
   `dv(1) − dv(b) < λ·glance_cost` → decline ("already covered by …").
2. **Worth looking?** Thompson-sample `usefulness[sig]`. If `sample · 0.5 < λ·glance_cost` → decline unseen. A 5% curiosity rate, rising with system pressure, keeps sidelined nodes from being locked out forever.
3. **Look and bid.** Glance → evidence → `p ~ Beta(competence[("g", evidence, sig)])`. Bid only if `dv(p) > λ·expected_cost`.

where `dv(p) = max(p·R − (1−p)·W, 0)` is the value of holding an answer you believe with probability `p` (you can always abstain), and `W = penalty·(1 + pressure)`.

### 3.2 Ranking

```
merit(bid) = dv( reading(p_mean) + (p_sample − p_mean) ) − λ·cost
```

`reading` is the peers' trust-adjusted view of the bidder's calibrated estimate. The bidder keeps its own exploration margin (Thompson sample minus mean) on top. Bids with `merit ≤ 0` are never called on, so if nobody can plausibly help, the council abstains without spending anything.

### 3.3 Solving, reviewing, escalating

The best bidder solves. Then, as lead, it decides for itself whether to buy a review, by value of information over the available reviewers:

```
P(endorse) = b·TNR + (1−b)·(1−TPR)
b_endorse  = b·TNR / P(endorse)
b_reject   = b·(1−TNR) / (1 − P(endorse))
VOI        = P(ans)·[P(endorse)·dv(b_endorse) + (1−P(endorse))·dv(b_reject)] + (1−P(ans))·dv(b) − dv(b)
ask the reviewer with the largest VOI − λ·review_cost, if positive
```

Confident leads rightly skip review. Uncertain leads buy it when a reviewer has shown it can tell right from wrong in this kind of situation. A 3% curiosity rate keeps reviewer statistics fresh.

A verdict updates the lead's belief by Bayes, using the lead's own learned TPR/TNR for that reviewer. A rejection may carry a **counter-proposal**, which becomes a candidate believed according to that reviewer's dissent record.

If the best candidate is still below the delivery bar, the next bidder with positive merit gets a turn (up to 3 proposals).

### 3.4 Reconciling conflicts

Two answers further apart than 2× tolerance can't both be right. Answers closer than that are grouped together and the most trusted one speaks for the group. For the remaining mutually exclusive groups with beliefs `p_i`:

```
P(group i is the right one) = p_i · Π_{j≠i}(1 − p_j) / Z,   Z = Π_j(1 − p_j) + Σ_k p_k Π_{j≠k}(1 − p_j)
```

Two confident, contradictory answers therefore pull each other down, which sends the council looking for more evidence or into abstention, instead of letting the louder node win.

### 3.5 Delivery and certification

Deliver the top candidate if its reconciled belief is at least `W/(R+W)` (0.5 when calm, higher under pressure). Otherwise abstain.

An unlabeled delivered answer with belief ≥ 0.8 and no rejection is **certified**: broadcast as a teaching signal. Each learner applies its own bar: memory only learns from ≥ 0.95, the noisy-data learner from ≥ 0.8, and the inducer only from its own exact laws.

### 3.6 Pressure

```
pressure = clip((recent_error − normal_error − 0.05) / 0.2, 0, 1)
```

It measures "worse than our own normal", not an absolute error level, so a world that's just noisy doesn't make the council permanently jumpy. Under pressure, every node raises its bar for delivering, values review more, and looks at tasks more often.

## 4. Settlement and learning

Every node sees the full transcript (`Record`). On labeled tasks:

- its own proposals update `competence` (three keys), the regression archive, the drift monitor and the surprise check;
- peers' proposals update its `ClaimCalibrator` (double weight if it took part) and its **concern** about that peer;
- reviews update its reviewer models (TPR, TNR, P(answer), dissent);
- with some probability, if it glanced but lost, it **quietly re-checks itself** on the labeled task (a shadow solve, billed as maintenance), so its self-model doesn't go stale;
- `learn()` absorbs the label.

On certified tasks, only `learn()` runs, and only if the learner's own bar is met.

## 5. Health lifecycle

```
            drift alarm / surprise (≥98% confident miss) / audit requested by a peer
healthy ──────────────────────────────────────────────────────► self-test
   ▲                                                              │
   │   passes (accuracy drop < 25%) → false alarm, back to work ◄─┤
   │                                                              │ fails
   │                                          repair() succeeded? ┤
   │                    yes: probation (shadow-checks only, 12 labeled tasks) ──► healthy
   │                    no:  quarantine (no bids, no reviews; retest every 30 tasks)
   │                                         retest passes → probation ──► healthy
```

- **Self-test** is a regression test: re-solve the last 40 archived labeled cases and compare with how well the node did on them at the time.
- On a confirmed fault the node **humbles** its self-model (shrinks all counts to 15%) and **announces** it was degraded. Every peer then drops its trust history for that node and **retracts** lessons learned from that node's certified answers in the last 120 tasks (Recall and Intuition keep provenance for this).
- **Audits.** A peer that sees confident failures (2 within a short window, or 1 shocking one, or 1 it had explicitly rejected in review) files an audit request, and the council relays it.

## 6. The nodes

### Intuition (`nodes/intuition.py`): neural
- 5 independent 2×32 tanh MLPs, vectorised, Adam with a Huber loss, trained on a replay buffer with per-member bootstrap.
- Works in a shape-only frame: `z = (window − last) / mean|Δ|`, predicting the next step.
- Predictive spread = √(ensemble variance + learned residual noise per situation) → raw P(within tolerance) → bucket → calibrated by `competence`.
- **Focus:** stores an example with probability `clip(2·P(I'm right here), 0.15, 1)`, so learning capacity goes where it can help. The floor lets it notice if it gets good somewhere new.
- Review = an independent second opinion: it solves the task itself and endorses if it lands within tolerance.

### Recall (`nodes/recall.py`): neural (associative memory)
- k-NN over normalised windows (k = 4), exact-match aware. Evidence = (distance: exact/near/mid/far, agreement: agree/split).
- Exact on shapes that repeat once normalised (every doubling sequence looks the same), and knows when it is guessing.
- Stores labels plus near-certain certified answers, with provenance for retraction. Repair = wipe and rebuild.

### Inducer (`nodes/inducer.py`): symbolic
- A grammar of 13 law templates (constant, arithmetic, geometric, periods, interleaved, affine, recurrences of order 2–3 with or without a constant, polynomials up to cubic). Each is fitted by least squares and snapped to simple rationals. A fit is exact if the residual is ~0.
- **Learned search order:** Dirichlet counts of confirmed laws per situation, plus a simplicity prior, decide what to try first.
- **Concepts:** a law with specific coefficients confirmed ≥ 4 times becomes a named concept, checked first at 0.05 compute.
- **Knows when not to reason exactly:** it learns P(an exact law exists | situation). Where that's < 5% (with 10% exploration), it switches to an approximate mode: its 3 historically best approximate laws, chosen by predictive spread with a mild Occam penalty. Its glance in that mode reports actual fit quality, so its bids are input-specific.
- Every answer ships with its law as the rationale.
- Review: re-derive from a few templates. Endorse or reject with the exact law as a counter-proposal, or abstain if no exact law is found.

### Critic (`nodes/critic.py`): symbolic
- Constraints: keeps-direction, keeps-curvature, bounded-step, constant-growth-ratio, stays-in-envelope.
- Learns P(reality satisfies the constraint | it applies, situation) from every label. It only vetoes using constraints at ≥ 90% reliability, so constraints that turn out to be folklore in some situation stop being used there.

## 7. Baselines and ablations (`experiment.py`)

- `neural-only`, `symbolic-only`: one node does everything (same node code, same learning, same self-healing).
- `hand-written gate`: integer-valued → inducer, else → intuition. That's the "programmatic gate".
- `synod w/o review | trust | exchange | self-healing`: switch one mechanism off.

## 8. Known limitations and next steps

- **Bidding overhead.** A market costs compute: Synod uses about 2.4 units per task against the gate's 1.1. Open-outcry and learned self-restraint cut this a lot. A learned "who usually wins here" prior could cut it further.
- **Echo risk in certification.** Learners only train on certified answers under their own bars, calibration only learns from real labels, and retraction cleans up after a confirmed fault. A node that's wrong in a way nobody can check is still only caught by labels.
- **Synthetic world.** The task domain is small and numeric. The protocol is domain-agnostic; nodes and `TaskView` are where a real domain plugs in.
- **Next:** an LLM node and a solver node on a real task, node spawning and retirement driven by marginal contribution, partial-credit composition (one node's output as another's input), and learned (not hand-picked) situation signatures.
