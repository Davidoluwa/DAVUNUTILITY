# Synod architecture

This is the detailed version: what every piece believes, how each decision is computed, and why.

## 1. Design rules

1. **No node sees the answer or the task family.** Nodes get a `TaskView` (history or question text, tolerance, system pressure, a coarse shared `context`). Labels arrive after delivery, for some tasks only.
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

A verdict says how sure the reviewer was (its `evidence`, e.g. `("unsure", "novel")`). It updates the lead's belief by Bayes, using the lead's own TPR/TNR for that reviewer, **keyed first by that evidence**, so a hesitant "no" isn't read with the weight of a confident one. A rejection may carry a **counter-proposal**, which becomes a candidate believed according to that reviewer's dissent record. Reviewers that aren't sure enough to object abstain rather than veto.

If the best candidate is still below the delivery bar, the next bidder with positive merit gets a turn (up to 3 proposals).

### 3.4 Reconciling conflicts

Two answers further apart than 2× tolerance can't both be right. Answers closer than that are grouped together and the most trusted one speaks for the group.

Each surviving belief is already *conditioned on the clash*: a rejected lead was updated by Bayes, and a counter-proposal is believed according to its author's record as a dissenter. So the beliefs are used as they are, and only rescaled if mutually exclusive answers add up to more than 100%:

```
S = Σ_groups p_g ;   p_g ← p_g / S   if S > 1
```

(An earlier version multiplied the beliefs as if they were independent opinions, `p_i·Π_{j≠i}(1−p_j)/Z`. That counted the same disagreement twice and let a confidently wrong reviewer crush a correct, novel answer.)

### 3.5 Delivery and certification

Deliver the top candidate if its reconciled belief is at least `W/(R+W)` (0.5 when calm, higher under pressure). Otherwise abstain.

An unlabeled delivered answer with belief ≥ 0.8 is **certified** as a teaching signal only if it is a **consensus**: no review rejected it and no rival answer appeared anywhere in the deliberation. Each learner then applies its own bar: memory only learns from ≥ 0.95, the noisy-data learner from ≥ 0.8, and the inducer only from its own exact laws. In maths, the reader never teaches itself from its own answers on ground that was novel to it, and the parser only adopts a peer's answer for a new wording if its own reasoning independently reaches the same answer ("no hearsay").

### 3.5b Asking for help

With a teacher and a budget (`CouncilConfig.help_budget`), the council asks for the true answer when it couldn't settle a question itself: it abstained after trying, or its members proposed answers that can't both be right. It asks *after* answering, so the asked question is scored as answered. The label is then used exactly like a training label, so the next question of that shape benefits. This is self-limiting: once a wording is learned, it stops being contested and stops triggering questions.

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

Before any of that, every node may post an **explanation** to `record.notes` via `explain()`. In maths, the parser posts the programs that reproduce the label, and the reader trains on them. That's how symbolic discoveries become neural skill.

When the council is answering rather than learning (`ask`/`chat`), nodes set `explore = False` and bid their calibrated beliefs instead of Thompson samples, so the same question gets the same answer.

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

## 6. The sequence nodes

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

## 7. The maths world (`synod/maths/`)

### 7.1 What the symbolic side knows and doesn't

`mathlang.read()` turns a question into typed **slots** (numbers N, lists L, equations Q, function definitions F, calls C, expressions X) and a **skeleton** (the wording with notation replaced by placeholders):

```
"Suppose 4*k - 6 = 10. What is the remainder when k is divided by 3?"
  slots     N1Q1   (the number 3; the equation 4k − 16 = 0)
  skeleton  suppose <eq> what is the remainder when <var> is divided by #
```

It can parse polynomials in one variable exactly (rational coefficients, implicit multiplication, powers) and tell the variable `x` from the word "a". That's all the built-in knowledge: notation, not language.

### 7.2 Programs and search

A program is a nested tuple over slots, e.g. `("mod", ("solve", ("Q", 0)), ("N", 0))`. There are 26 primitives: arithmetic, mod, gcd, lcm, powers, comparisons, primality, square and sqrt; list mean, median, total, max, min and next term (reusing the sequence inducer); and `calc`, `solve`, `apply`, `at`, `slope` for notation. Unit facts are constants K ∈ {2, 3, 4, 5, 7, 10, 12, 24, 60, 100, 1000}.

`explain(reading, answer)` enumerates depth-1 programs, and depth-2 compositions if no simple program uses every slot, keeping those that reproduce the answer (≈3 ms per question).

### 7.3 Parser: three ways to answer

1. **Known wording.** A version space per skeleton, `program → [hits, misses]`, updated on every labeled example. The best program is the one consistent with the most examples.
2. **Analogy.** For an unfamiliar wording, take the most similar known wordings with the same slots (IDF-weighted Jaccard), their programs, and every program **one edit away** (swap an operation for a sibling, flip argument order, change a constant).
3. **Composition.** If no analogy scores well, enumerate fresh programs that use every slot.

All candidates are scored by learned word meanings:

```
assoc(w, p) = P(p | w) · PMI(w, p)            (plain PMI over-rates rare primitives)
score(prog) = Σ assigned assoc  − 1 per primitive  − 0.7 · Σ strong words left unexplained
```

Each word may justify at most one primitive (explaining away). A word whose favourite primitive is already in the program counts as explained (synonyms). Analogies get a bonus of 2 × similarity, edits pay 0.75. The evidence the parser bids on is `(mode, closeness, margin)`, calibrated separately for each.

### 7.4 Reader, estimator, checker

- **Reader:** 3 sparse MLPs (hashed unigrams and bigrams of the skeleton → softmax over discovered programs), trained on the parser's explanations. Its evidence is `(novel/familiar, agree/split, confidence)`. *Novel* means the combination of words its networks rely on (large learned input weights) has never been seen, so a new name in a word problem doesn't count but a new pairing of operation words does.
- **Estimator:** predicts `sign·log10(1+|answer|)` from the wording and numeric features. Rejects answers outside ~2.5 learned standard deviations; abstains on unfamiliar wording.
- **Checker:** satisfies-the-equation, whole-number, yes-or-no and inside-the-list checks, with reliability learned per check, context and wording. It vetoes only at ≥ 97%.

### 7.5 Curriculum and tests

36 training question types (arithmetic in words and symbols, mod, gcd, lcm, primes, powers, roots, linear equations, function evaluation, derivatives, sequences, list statistics, comparisons, unit conversion, word problems, two-step compositions). Each has training phrasings and held-out phrasings. Word problems use held-out names and objects at test time. Compositions at test time are 4 more types, combinations never seen in training.

## 8. Baselines and ablations

Sequences (`experiment.py`):

- `neural-only`, `symbolic-only`: one node does everything (same node code, same learning, same self-healing).
- `hand-written gate`: integer-valued → inducer, else → intuition. That's the "programmatic gate".
- `synod w/o review | trust | exchange | self-healing`: switch one mechanism off.

Maths (`maths/experiment.py`): `parser alone`, `reader alone` (still trained on the parser's explanations, since it can't discover programs itself), a `hand-written gate` (parser if it knows the wording, else reader), and Synod with and without a teacher.

## 9. Known limitations and next steps

- **Self-knowledge doesn't transfer to harder novelty.** On never-seen maths compositions, the reader is confidently wrong. Its "novel ground" record comes from training-time novelty, which was easier. Without feedback the council can't know it's in a harder regime: alone, the parser is right 51% and never wrong there, while the council is right 10% and wrong 39%. A teacher on call fixes most of it (87%). Better unsupervised novelty and calibration is the next frontier.
- **Bidding overhead.** A market costs compute (sequences: 2.5 units per task vs the gate's 1.1).
- **Echo risk in self-training.** Mitigated by consensus-only certification, per-learner bars, no-hearsay corroboration, no self-teaching on novel ground, and retraction after a confirmed fault, but not eliminated.
- **Synthetic worlds.** Both domains are generated. The protocol is domain-agnostic; nodes, `TaskView` and the answer check are where a real domain plugs in.
- **Next:** an LLM as a neural reader and a real CAS/SMT solver as a symbolic node; the teacher replaced by a stronger model or a human; node spawning and retirement driven by marginal contribution; learned (not hand-picked) situation signatures.
