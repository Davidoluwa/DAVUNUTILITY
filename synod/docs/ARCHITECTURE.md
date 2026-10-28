# Synod architecture

This is the detailed version: what every piece believes, how each decision is computed, and why. The council's decisions are learned (a router and a judge, trained like a mixture-of-experts gate); the members' self-knowledge and health are the nodes' own.

## 1. Design rules

1. **No node sees the answer or the task family.** Nodes get a `TaskView` (history or question text, tolerance, a coarse shared `context`, and the task's `features`). Labels arrive after delivery, for some tasks only.
2. **No hand-written decision rules in the council.** Whom to ask, whether a review is worth it and which answer to trust are learned models, trained on outcomes during training. The council only runs the steps and does the bookkeeping.
3. **One objective for everyone.** `U = +1 correct, −1 wrong, 0 abstain, −λ·compute` with λ = 0.02. The router's consult rule and the judge's delivery threshold both come straight from it.
4. **Only labels that arrive on their own calibrate anything.** Answers the council asked a teacher for are a biased sample (it asked exactly where it was unsure), so they teach knowledge and never train the router, the judge, or any member's self-model.

## 2. Beliefs (`beliefs.py`, `learner.py`)

### Competence: P(success | situation)

A hierarchical Beta-Bernoulli model over tuple keys. Every prefix of a key is its own cell, and a cell's prior is its parent's posterior mean with pseudo-count `s`:

```
m_0 = prior
m_k = (a_k + s·m_{k-1}) / (a_k + b_k + s)      for each prefix k of the key
```

Sparse situations borrow from broader ones and specialise as evidence arrives. Counts decay on update (γ ≈ 0.995), so beliefs follow a changing world. Each node keeps `competence` over `("ctx", *sig)` and `("p", *proposal_evidence, *sig)`: how often am I right here, given what I saw? Its confidence on every proposal is read from the second key, so raw scores (ensemble spread, residual fits, memory distance) only pick a bucket and the probability is learned from outcomes (contextual histogram-binning calibration). Checkers and critics keep the same kind of model for how often each of their rules holds.

`sig` is a coarse description of the task's shape (sequences: precision, integer/real, smooth/rough, growth; maths: slot pattern and number sizes). See `perception.py` and `maths/mathlang.py`.

### SparseLogLinear: the council's learner

The router, the judge and the reviewer-value model are each a linear model over string features (`"e|parser|analogy"`, `"x|reader|w:times"`), trained online with a per-feature Adagrad step whose accumulator decays (0.999), so it never stops adapting. `reasons()` returns the features that pushed a score hardest, which is what the transcripts and the viewer show as "why it trusted …".

### DriftMonitor

A one-sided CUSUM on `confidence − outcome − slack`. A calibrated node drifts to zero; a node that's suddenly worse than it believes crosses the threshold in a few labeled outcomes.

## 3. The meeting (`council.py`)

### 3.1 Task features

The router and judge see the task's features: in maths, the context tokens plus every word of the question's skeleton (`w:times`, `w:remainder`, …), like the token features an MoE gate sees. In sequences, the shape signature. Switching them off (`synod w/o task features`) leaves only per-member biases.

### 3.2 The router and its cascade

One logistic model per solver: `π_n = σ(w · f_route(n, task))`, trained with cross-entropy on whether that member's answer was right, every time it was consulted on a labeled task.

Solvers are ranked by `π` and consulted in order. The next one is consulted only if its expected contribution beats its compute:

```
P(all consulted so far are wrong) · π_n · (R + W)  ≥  λ · typical_cost_n
```

`typical_cost_n` is a running average of what that member actually spent. On 10% of training tasks (`explore`) everyone is consulted, so the router keeps seeing what members it would have skipped would have said.

### 3.3 Reviewer routing

Reviewers (checker, estimator, critic) report signals on each distinct candidate. Whether one is worth asking is a learned regression: on every dense, labeled training task, the council replays the judge's decision with and without that reviewer's signals and records the utility difference. The model predicts that gain from the reviewer, the task's features, how many rival answers there are, which members proposed what, and how unsure the judge already is without reviews. A reviewer is asked when the predicted gain ≥ `λ · its cost · number of candidates`.

### 3.4 The judge

A softmax gate over every candidate answer plus a "none of these" option. Each candidate's logit is `w · f_cand`, where the features are:

- who proposed it (`b|node`), its self-confidence (as a value and a bucket) and every prefix of its evidence;
- the task's features, alone and crossed with the member and its evidence head (`ex|reader|r/novel|w:times`), so trust can depend on the kind of question;
- who agrees and who disagrees with it, with their evidence, and how many agree;
- every reviewer signal on it (`v|parser|checker|whole-number:pass:trusted`);
- how many rival answers are on the table.

"None of these" has its own features (a bias, the task's features, what was offered). Members whose answers agree within tolerance form one group and pool their gates, so the probability of an answer is the sum over its group.

Training maximises the probability of the truth: `−log Σ_{k ∈ right} g_k`, or `−log g_none` when nobody was right. The gradient on logit k is `g_k − 1[k ∈ right]·g_k / Σ_{right} g`.

### 3.5 Delivery, teaching and asking for help

Deliver the most probable group's answer if its probability is at least `W/(R+W)` = 0.5. Otherwise abstain.

An unlabeled answer the judge gives ≥ 0.9 (`teach_at`) becomes **certified** teaching signal. Members decide what to do with it (the inducer only takes its own exact laws; recall and intuition keep provenance so they can retract it later).

With a teacher and a budget (`help_budget`), the council asks for the answer after a question it couldn't settle: it abstained after trying, or its members proposed rival answers. Asked labels go to every member's `learn(…, "asked")` as knowledge only (rule 4).

### 3.6 What the record shows

Every decision is written to `record.notes["council"]`: the router's probability for every solver, why each skipped member was skipped, each candidate's gate and top reasons, the pooled groups and the "none" weight. `transcript.py` renders it, and `maths/trace.py` turns a whole exam into the viewer.

## 4. Settlement and learning

Every node sees the full transcript (`Record`). Before anything else, every node may post an **explanation** to `record.notes` via `explain()`. In maths, the parser posts the programs that reproduce the label, and the reader trains on them. That's how symbolic discoveries become neural skill.

On labels that arrived on their own:

- the router and judge take one gradient step (3.2, 3.4), and on dense tasks the reviewer-value model too (3.3);
- each node's own proposal updates its `competence`, its regression archive, its drift monitor and its surprise check;
- each node watches its peers: a confident failure raises its concern about that peer, and enough concern files an audit request;
- on probation, a node quietly re-solves labeled tasks it wasn't asked about (billed as maintenance);
- `learn(…, "label")` absorbs the label.

On asked labels, only `learn(…, "asked")` runs. On certified answers, only `learn(…, "certified")` runs.

## 5. Health lifecycle

```
            drift alarm / surprise (≥98% confident miss) / audit requested by a peer
healthy ──────────────────────────────────────────────────────► self-test
   ▲                                                              │
   │   passes (accuracy drop < 25%) → false alarm, back to work ◄─┤
   │                                                              │ fails
   │                                          repair() succeeded? ┤
   │                    yes: probation (shadow-checks only, 12 labeled tasks) ──► healthy
   │                    no:  quarantine (not available to the router; retest every 30 tasks)
   │                                         retest passes → probation ──► healthy
```

- **Self-test** is a regression test: re-solve the last 40 archived labeled cases and compare with how well the node did on them at the time.
- On a confirmed fault the node **humbles** its self-model (shrinks all counts to 15%) and **announces** it was degraded. Every peer then **retracts** lessons learned from that node's certified answers in the last 120 tasks (Recall and Intuition keep provenance for this). A quarantined node isn't available, so the router simply can't ask it.
- **Audits.** A peer that sees confident failures (2 within a short window, or 1 shocking one) files an audit request, and the council relays it.

## 6. The sequence nodes

### Intuition (`nodes/intuition.py`): neural
- 5 independent 2×32 tanh MLPs, vectorised, Adam with a Huber loss, trained on a replay buffer with per-member bootstrap.
- Works in a shape-only frame: `z = (window − last) / mean|Δ|`, predicting the next step.
- Predictive spread = √(ensemble variance + learned residual noise per situation) → raw P(within tolerance) → bucket → calibrated by `competence`.
- **Focus:** stores an example with probability `clip(2·P(I'm right here), 0.15, 1)`, so learning capacity goes where it can help. The floor lets it notice if it gets good somewhere new.

### Recall (`nodes/recall.py`): neural (associative memory)
- k-NN over normalised windows (k = 4), exact-match aware. Evidence = (distance: exact/near/mid/far, agreement: agree/split).
- Exact on shapes that repeat once normalised (every doubling sequence looks the same), and knows when it is guessing.
- Stores labels plus near-certain certified answers, with provenance for retraction. Repair = wipe and rebuild.

### Inducer (`nodes/inducer.py`): symbolic
- A grammar of 13 law templates (constant, arithmetic, geometric, periods, interleaved, affine, recurrences of order 2–3 with or without a constant, polynomials up to cubic). Each is fitted by least squares and snapped to simple rationals. A fit is exact if the residual is ~0.
- **Learned search order:** Dirichlet counts of confirmed laws per situation, plus a simplicity prior, decide what to try first.
- **Concepts:** a law with specific coefficients confirmed ≥ 4 times becomes a named concept, checked first at 0.05 compute.
- **Knows when not to reason exactly:** it learns P(an exact law exists | situation). Where that's < 5% (with 10% exploration), it switches to an approximate mode: its 3 historically best approximate laws, chosen by predictive spread with a mild Occam penalty. In that mode its evidence reports the actual fit quality, so its confidence is input-specific.
- Every answer ships with its law as the rationale.

### Critic (`nodes/critic.py`): symbolic
- Constraints: keeps-direction, keeps-curvature, bounded-step, constant-growth-ratio, stays-in-envelope.
- Learns P(reality satisfies the constraint | it applies, situation) from every label. It reports every applicable constraint as kept or broken, and as trusted (≥ 90% reliable here) or weak. The judge learns what each report is worth.

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

Each word may justify at most one primitive (explaining away). A word whose favourite primitive is already in the program counts as explained (synonyms). Analogies get a bonus of 2 × similarity, edits pay 0.75. The evidence the parser reports is `(mode, closeness, margin)`, and its confidence is calibrated separately for each.

### 7.4 Reader, estimator, checker

- **Reader:** 3 sparse MLPs (hashed unigrams and bigrams of the skeleton → softmax over discovered programs), trained on the parser's explanations. Its evidence is `(novel/familiar, agree/split, confidence)`. *Novel* means the combination of words its networks rely on (large learned input weights) has never been seen, so a new name in a word problem doesn't count but a new pairing of operation words does.
- **Estimator:** predicts `sign·log10(1+|answer|)` from the wording and numeric features. Reports how far a candidate is from its guess, in its own learned standard deviations (`size:close | loose | far | way-off`), and how much of the wording it has seen (`seen:familiar | partly-new | new`).
- **Checker:** satisfies-the-equation, whole-number, yes-or-no and inside-the-list checks, with reliability learned per check, context and wording. Reports each check as pass or fail, and as trusted (≥ 97% here) or weak.

### 7.5 Curriculum and tests

36 training question types (arithmetic in words and symbols, mod, gcd, lcm, primes, powers, roots, linear equations, function evaluation, derivatives, sequences, list statistics, comparisons, unit conversion, word problems, two-step compositions). Each has training phrasings and held-out phrasings. Word problems use held-out names and objects at test time. Compositions at test time are 4 more types, combinations never seen in training.

### 7.6 The exam

`maths/exam.py` holds 40 hand-written questions with an answer key checked by an independent unit test, plus a check that none appear word for word in training. The council is trained on the curriculum only and frozen (router and judge fixed, no certified-answer learning, no teacher). Each question goes to a fresh copy, so order can't matter.

## 8. Baselines and ablations

Sequences (`experiment.py`):

- `neural-only`, `symbolic-only`: one node does everything (same node code, same learning, same self-healing).
- `hand-written gate`: integer-valued → inducer, else → intuition. That's the "programmatic gate".
- `synod w/o task features | reviewers | exchange | self-healing`: switch one mechanism off.

Maths (`maths/experiment.py`): `parser alone`, `reader alone` (still trained on the parser's explanations, since it can't discover programs itself), a `hand-written gate` (parser if it knows the wording, else reader), and Synod frozen after training, still learning from its confident answers, and with a teacher. The maths report also gives each council's **ceiling**: how often at least one consulted member had the right answer.

Every comparison between versions of the council used 10 seeds. Held-out maths types flip as a whole family, so 5-seed means can move by 5 points on noise alone.

## 9. Known limitations and next steps

- **It doesn't know what it doesn't know.** The judge's trust was learned on the curriculum, so on questions outside it ("What is the gcd of 84 and 126?", "Calculate 15% of 80") it answers confidently and wrongly, where v1's hand-written novelty rules abstained. On never-seen combinations, 29% of answers are wrong where the parser alone is never wrong. The natural fix is to train the null option on data it can learn from: questions none of its members can answer (outlier exposure), or members held back from some question types during training so the judge sees what new ground looks like.
- **Tried and cut: uncertainty-aware routing.** Routing on estimate + standard deviation (optimism under uncertainty), and a learned familiarity signal (how many of the question's words the council has rarely met), were both implemented and evaluated over 10 seeds. Neither beat the plain council on the new-wording test sets (0.757 and 0.743 vs 0.805), so both were removed. Familiarity did get the right member asked more often; the judge didn't exploit it.
- **The judge is slow to drop a member that suddenly breaks.** Its Adagrad steps shrink with experience, so after the inducer's bug it keeps trusting it until the inducer quarantines itself (30% wrong in that window, vs 18% for v1's fast-decaying trust maps). Self-healing carries the fault response now.
- **Compute.** The cascade asks several members when it's unsure (sequences: 3.2 units per task vs the gate's 1.1).
- **Echo risk in self-training.** One rule now (teach from answers the judge gives ≥ 0.9), plus retraction after a confirmed fault. Learning from its own confident answers at test time doesn't help: word problems drop from 93% (frozen) to 89%.
- **Synthetic worlds.** Both domains are generated. The protocol is domain-agnostic; nodes, `TaskView`, task features and the answer check are where a real domain plugs in.
- **Next:** outlier exposure for the judge; an LLM as a neural reader and a real CAS/SMT solver as a symbolic node; the teacher replaced by a stronger model or a human; node spawning and retirement driven by how often the judge relies on each member.
