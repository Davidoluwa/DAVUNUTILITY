# Synod

**A council of neural and symbolic experts. A learned router decides whom to ask and a learned judge decides which answer to trust. Both are trained on outcomes, like the gate in a mixture of experts. Nobody hand-writes who handles what.**

Synod is a working prototype of a neurosymbolic intelligence system where:

- there are many **nodes**, each either neural (learned, approximate, fast) or symbolic (explicit, exact, explainable);
- every node is responsible for the **efficiency and reliability of the whole system**: it knows how good it is where, learns from the council's outcomes, watches its peers and heals itself;
- who does what is **not a programmed gate**. A router and a judge are trained during training, from which answers turned out right, the way a mixture-of-experts layer trains its gate;
- the symbolic nodes **learn and adapt** too: they learn how to search, invent concepts, learn what words mean, and revise their beliefs.

The same council runs in two worlds:

1. **Sequences**: "what comes next?" tasks with faults and distribution shift injected on purpose. This world shows the self-organisation and self-healing.
2. **Maths**: the council learns what maths questions *mean* purely from answered examples, then answers new ones, including wordings, word problems and combinations it has never seen.

Plain Python + NumPy, no other dependencies.

```bash
cd synod
python -m synod.maths train                 # learn maths (~1 min), test it, save the council
python -m synod.maths ask "Suppose 2*n + 6 = 20. What is n times 8?"
python -m synod.maths chat                  # ask questions interactively
python -m synod.maths report --seeds 10     # compare strategies -> results/MATHS_REPORT.md
python -m synod.maths exam                  # 40 hand-written questions -> results/EXAM_REPORT.md
python -m synod.maths trace                 # every exam deliberation, step by step -> results/council_viewer.html
python -m synod --seeds 10                  # the sequence world -> results/REPORT.md
python -m unittest discover -s tests -t .   # 35 tests
```

---

## From the raw idea to mechanisms

| The idea | How Synod does it | Where |
|---|---|---|
| Many nodes, neural or symbolic | Sequences: `intuition` (MLP ensemble), `recall` (associative memory), `inducer` (program induction), `critic` (soft constraints). Maths: `reader` (neural), `estimator` (neural number sense), `parser` (symbolic), `checker` (symbolic). | `synod/nodes/`, `synod/maths/nodes.py` |
| Each node optimizes efficiency **and** reliability of the whole | One shared `Objective` (+1 right, −1 wrong, 0 abstain, −0.02 per unit of compute). The router, the judge and the nodes' own decisions (learn, self-test, quarantine) all serve it. | `objective.py`, `council.py`, `node.py` |
| Orchestrated to their strengths, not gated | A **learned router** predicts, from the task's features, how likely each member is to be right, and consults them most promising first while a second opinion is worth its compute. A **learned judge** weighs the candidates. Nobody writes "noisy → neural" or "equation → solver". | `council.py`, `learner.py` |
| Autonomous interoperability | Members report calibrated confidence and evidence. Reviewers report **signals, not vetoes**, and the judge learns what each signal is worth. Members **teach** each other from answers the judge is sure of, **audit** each other, and **retract** lessons from a peer that broke. | `council.py`, `node.py` |
| Symbolic parts aren't dumb and stiff | The sequence inducer learns per-situation search priors, invents concepts, and knows when exact laws don't exist. The maths parser learns what words mean, reasons by analogy, and composes programs for combinations it has never seen. Critics learn how far to trust each of their own rules. | `nodes/inducer.py`, `maths/nodes.py` |

## How a task flows

```
 task features (words, shape) ──► router: P(member is right here), one learned logistic per member
                                   │
       ask the most promising member; ask the next only if
       P(all asked so far are wrong) × P(it's right) × (reward + penalty) ≥ cost weight × its compute
                                   │
       reviewers: ask one if the value its signals have had in spots like this beats its compute
       (learned by replaying the judge's decision with and without it)
                                   │
 judge: softmax gate over every candidate + "none of these"
        reads who proposed it, their confidence and evidence, the task's features,
        who agrees or disagrees, and every reviewer signal; agreeing members pool their weight
                                   │
        deliver the most probable answer if it clears 0.5 (the objective's break-even), else abstain
                                   │
 label arrives (sometimes) ──► router and judge take one gradient step (only on labels the council didn't ask for)
                           ──► members update self-models, learn, self-test, quarantine, retract
 no label, judge ≥ 0.9     ──► the answer becomes teaching signal for the members
```

On 10% of training tasks the router consults everyone, so it keeps learning from full information (MoE-style dense exploration).

---

# Part 1: sequences, self-organisation and self-healing

| Node | Kind | Good at | Learns | Breaks and heals |
|---|---|---|---|---|
| `intuition` | neural (5-member MLP ensemble) | noisy, nonlinear series | labels + confident council answers; spends its learning capacity where its own record says it can help | weights corrupted → retrain from replay |
| `recall` | neural (associative memory) | shapes it has seen, compiled from what the inducer taught it | stores labels + confident answers, with provenance | index corrupted → wipe and rebuild |
| `inducer` | symbolic (program induction over a grammar of laws) | exact laws: recurrences, polynomials, periodicities | search priors, concepts, where exact laws exist | can't fix its own code → quarantines itself until a hotfix passes its self-test |
| `critic` | symbolic (soft constraints) | cheap sanity checks | how often reality respects each constraint, per situation | — |

Scenario: 1600 tasks from 9 hidden families, only 35% ever labeled. At **t=550** Recall's memory is corrupted (it stays confident while wrong). At **t=1000** a never-seen family appears. At **t=1250** the Inducer gets a bug (+1 on every answer), and at **t=1400** a hotfix ships.

10 seeds, utility per task (higher is better):

| strategy | utility | accuracy | wrong | compute | right after memory fault | right after symbolic bug |
|---|---|---|---|---|---|---|
| **Synod** | **+0.662** | 84% | 11% | 3.22 | +0.67 (11% wrong) | +0.23 (30% wrong) |
| symbolic-only | +0.633 | 73% | 6% | 1.85 | +0.69 | −0.05 |
| hand-written gate | +0.513 | 62% | 9% | 1.05 | +0.49 | −0.02 |
| neural-only | +0.082 | 19% | 8% | 1.50 | +0.10 | +0.14 |
| Synod w/o task features | +0.647 | 84% | 11% | 3.91 | +0.64 | +0.26 |
| Synod w/o reviewers | +0.664 | 84% | 12% | 3.09 | +0.68 | +0.25 |
| Synod w/o exchange | +0.649 | 83% | 11% | 3.29 | +0.61 (14% wrong) | +0.18 |
| Synod w/o self-healing | +0.620 | 81% | 12% | 3.52 | +0.58 (15% wrong) | −0.11 (39% wrong) |

- **The router learned a division of labour nobody wrote down.** Families are hidden. The inducer ended up owning every exact family, and intuition took over saturating curves after the faults (87% of them).
- **Self-healing is still the biggest single win.** Recall caught its own corruption 2 tasks in, after a peer asked for an audit, and rebuilt itself. The Inducer was surprised by a 99%-confident miss 23 tasks after its bug and quarantined itself. Its peers retracted 89 lessons it had taught them, and it came back after the hotfix.
- **Task features matter.** Without them the router can't tell situations apart, so it asks more members (compute 3.91 vs 3.22) for a worse result.
- **Reviewers are break-even here** (+0.664 without, ±0.03 between seeds). The judge learns what the critic's signals are worth, and here it isn't much.
- **Caveats.** Right after the symbolic bug, the learned judge keeps trusting the inducer until it quarantines itself (30% wrong in that window, vs 18% for v1's hand-built trust model). Overall, v1 scored +0.671 (5 seeds), level with v2 within noise. Compute is higher than the gate's: the council asks several members when it's unsure.

A deliberation (two neural members outvote the symbolic law, correctly):

```text
task #307  [10.06, 10.09, 10.61, 12.02, 17.1, 26.99, 41.28, 51.36, ?]  tolerance ±1.9  (hidden family: saturating)
  critic    not consulted (router: its opinion here is worth -0.040, less than its compute (0.016))
  recall    consulted (router 72%): 57.43  self-confidence 0.55  gate 0.88  because recalls far match -> 57.43
  intuition consulted (router 66%): 56.5  self-confidence 0.62  gate 0.05  because ensemble says 56.50 ± 7.84
  inducer   consulted (router 56%): 68.33  self-confidence 0.00  gate 0.02  because ~x[n] = 1.33*x[n-1]  (best approximate law, sd 5.05)
  judge: 56.5 ← intuition+recall: 0.93  68.33 ← inducer: 0.02   none of these: 0.05   (deliver at ≥ 0.50)
     why it trusted recall: +0.3 vs|recall|inducer|approx/c1, +0.3 ag|recall|1, +0.2 with|recall|intuition, +0.2 e|recall|m/far/split
  => answers 57.43 from recall (probability 0.93)  [truth 55.8: correct]  compute 3.6
```

---

# Part 2: Synod does maths

**Nobody tells the system what any wording means.** It gets 4,000 practice questions in the style of DeepMind's Mathematics Dataset (half with the answer revealed afterwards), then is tested on 1,250 questions with **no answers at all**.

| Node | Kind | What it knows | What it learns |
|---|---|---|---|
| `parser` | symbolic | how to *read notation* (numbers, lists, polynomials, equations, `f(x)=…`) and 26 exact operations, in rational arithmetic. **No English.** | Searches for the program that reproduces each answer, keeps a version space per wording, and learns word → operation meanings. Answers unfamiliar wordings by **analogy** ("like that one, but 'times' instead of 'plus'") or by **composing** programs from word meanings. |
| `reader` | neural (3-net ensemble over word n-grams) | nothing | Wording → program, trained on what the parser discovers. Generalises to paraphrases, and knows when a combination of important words is new to it. Execution stays exact. |
| `estimator` | neural | nothing | Number sense: the rough size of an answer. Reports how close each candidate is, and how familiar the question looks. |
| `checker` | symbolic | back-substitution, whole-number and yes/no checks | How reliable each check is for each wording. Reports pass/fail and whether it trusts each check here. |

### Results (10 seeds; % right, wrong in brackets, the rest are abstentions)

The council is frozen after training: no learning at test time, same as the baselines.

| strategy | familiar wording | new wording | numbers 100× bigger | word problems* | new combinations |
|---|---|---|---|---|---|
| **Synod** | **100% (0%)** | **85% (6%)** | **100% (0%)** | **93% (4%)** | **64% (29%)** |
| parser alone (symbolic) | 100% (0%) | 70% (5%) | 100% (0%) | 76% (0%) | 44% (0%) |
| reader alone (neural) | 98% (0%) | 81% (9%) | 97% (0%) | 61% (10%) | 1% (80%) |
| hand-written gate | 100% (0%) | 67% (7%) | 99% (0%) | 56% (7%) | 1% (72%) |
| Synod v1 (hand-designed auction, 3 seeds) | 100% (0%) | 75% (7%) | 99% (0%) | 63% (7%) | 10% (39%) |

\* new names, new objects and new phrasings.

What this shows:

- **The council beats every member alone and the hand-written gate on every new kind of question.** On word problems it gets 93% where the best single member gets 76%. On new combinations it gets 64% where the parser alone gets 44%.
- **It uses nearly everything its members know.** On new combinations, 64% right out of a 64% ceiling (at least one member had the right answer). On word problems, 93% of 97%. The remaining gap is the judge's to close.
- **Exact symbolic execution doesn't care how big the numbers are**: 100% on numbers far outside training.
- **The frontier.** On new combinations, 29% of answers are wrong where the parser alone is never wrong (it abstains instead). The judge learned its trust on familiar ground. It hasn't learned to be more careful on new ground.
- **High variance between seeds.** Word problems range from 51% to 100% across seeds and new combinations from 47% to 81%, because each held-out type has one wording and a whole type flips together. Use 10 seeds before believing a 5-point difference.

### A 40-question exam

40 hand-written questions on curriculum topics, none taken from the generator: new numbers throughout, 18 in wordings never seen in training, some with numbers outside the training ranges. The council was trained on the curriculum only, then frozen for the exam (`results/EXAM_REPORT.md`).

| | right | wrong | abstained |
|---|---|---|---|
| **Synod** | **37/40** | 3 | 0 |
| Synod v1 | 34 | 4 | 2 |
| parser alone | 31 | 2 | 7 |
| reader alone | 34 | 4 | 2 |
| hand-written gate | 34 | 3 | 3 |

Every familiar wording right (22/22) and 15/18 new wordings. The three misses: "Find the difference between 900 and 456" (−444, wrong order), a baker sharing rolls into trays (0), and "the least common multiple of 4 and 6, minus 5" (10). The **[council viewer](results/council_viewer.html)** shows every exam question step by step: what each member privately worked out, whom the router asked, what the reviewers reported, and the judge's weighted reasons.

### Asking it questions it was never trained on

```text
What is 17 times 23?                                         -> 391
Is 221 a prime number?                                       -> 0 (no: 13 × 17)
What is the remainder when 1000 is divided by 7?             -> 6
Let f(x) = x^2 + 3*x - 1. What is f(5)?                      -> 39
What comes next: 2, 6, 18, 54, 162, 486?                     -> 1458
Differentiate 4*x^3 - x with respect to x and evaluate at x = 2.  -> 47
What is 2 to the power of 20?                                -> 1048576
How many hours are there in 3 days?                          -> 72
Zara has 12 mangoes and buys 9 more. How many mangoes does Zara have?   -> 21
Suppose 2*n + 6 = 20. What is n times 8?                     -> 56
What is the square root of 144 plus 5?                       -> 17
If I have 3 boxes with 12 eggs in each box, how many eggs are there?   -> 36
What is 7 squared minus 9?                                   -> 40
What is the capital of France?                               -> abstains (nobody can read it)
What is the gcd of 84 and 126?                               -> 252, wrong (that's the lcm; "gcd" was never taught)
Calculate 15% of 80.                                         -> 1200, wrong (percent wasn't in the curriculum)
```

The last two are the open problem in one place: v1 abstained on them through hand-written novelty rules. The learned judge never saw an out-of-scope question in training, so it never learned what one looks like.

A deliberation:

```text
Q #4750: Kofi had 29 cards and used 8. How many cards remain?  (hidden type: story_sub)
  reader    consulted (router 100%): 21  self-confidence 0.99  gate 0.91  because (n1 - n2)  [reads like it, p=0.98, ensemble agrees]
  parser    consulted (router 99%): 21  self-confidence 0.99  gate 0.09  because (n1 - n2)  [like 'kofi had # stamps and used # how many stamps remain' (0.69); cues: 'had'->sub]
     estimator on 21: I'd guess about 28.2; this is close (new question)
     checker on 21: whole-number pass:trusted, yes-or-no fail:weak
  judge: 21 ← reader+parser: 1.00   none of these: 0.00   (deliver at ≥ 0.50)
     why it trusted reader: +0.5 cl|reader, +0.4 x|reader|ctx:N2, +0.4 x|reader|ctx:multi, +0.4 cb|reader|9
  => answers 21 from reader (probability 1.00)  [truth 21: correct]  compute 1.5
```

### What the parser learned words mean (from answers alone)

`remainder, modulo → mod` · `derivative, differentiate → slope` · `root → sqrt` · `mean, average → mean` · `greatest, divisor, factor → gcd` · `multiple, least, smallest → lcm` · `away, gives, left → subtract` · `times, multiplied → multiply` · `power, raised → pow` · `suppose → solve` · `next, comes, sequence → next term`

…plus some spurious ones that show it's statistics, not magic: `friends → divide` (from "shared equally between friends"), `or → max`, `whether → is_prime`.

---

## What changed from v1, and what got cut

v1 ran a hand-designed auction. Each node decided whether to look and bid, and the bids were ranked through each peer's trust map. A lead then bought reviews by a value-of-information formula, and rival answers were reconciled by a fixed rule. Every one of those steps was a formula someone wrote. v2 replaces the decision-making with two models trained on outcomes, and deletes the rest:

| cut | replaced by |
|---|---|
| glance/bid auction, curiosity rates, "already covered" rule | the learned router and its cost-aware cascade |
| peer trust maps (`ClaimCalibrator`), median-of-peers reading | judge features: who proposed it, their confidence, evidence and agreement |
| value-of-information review purchase, reviewer TPR/TNR and dissent models | reviewer value learned by counterfactual replay |
| reviewer vetoes and counter-proposals | reviewers report signals; the judge learns what they're worth |
| conflict reconciliation rule | softmax gate with "none of these"; agreeing members pool weight |
| consensus-only certification, per-learner bars, "no hearsay", "no self-teaching on novel ground" | one rule: teach from answers the judge gives ≥ 0.9 |
| system pressure | (gone) |

Teacher answers (labels the council asked for) are knowledge only. They never train the router or judge, or calibrate any member, because the council chose which questions to ask and that sample is biased.

Two principled additions were tried and **cut** because they didn't earn their place over 10 seeds (mean accuracy over the three new-wording test sets; without either: 0.805 ± 0.021):

- *Optimism under uncertainty*: route on the router's estimate plus its standard deviation, so the council asks more members where its estimates rest on little evidence. 0.757 ± 0.028, with more compute. It looked like a big win on 5 seeds, which is how the variance above fools you.
- *A learned familiarity signal*: how many of a question's words the council has rarely met, so the router and judge can learn from first encounters how to act on new ground. 0.743 ± 0.019 on its own. With optimism as well, the right member was asked on 100% of word problems, but the judge didn't turn that into accuracy (0.749 ± 0.027).

## Plugging in real nodes

A node is anything that implements a few methods (see `synod/node.py`):

```python
class MyNode(Node):
    kind = NEURAL            # or SYMBOLIC
    solves = True            # False for a pure reviewer
    def solve(self, view):   # -> Proposal(value, confidence, cost, rationale, evidence, program)
    def critique(self, view, proposal):  # reviewers -> Verdict(evidence=("signal:value", ...))
    def learn(self, view, value, source, record):  # source: "label" | "asked" | "certified"
    def explain(self, record):  # optional: share an explanation with the others
    def repair(self):        # try to fix yourself; return True if you did
```

Self-models, drift detection, self-tests, audits, quarantine, probation and retraction come from the base class. The router and judge learn what a new node is good at from outcomes, with no other changes. Natural next nodes: an LLM call as a neural reader, a real CAS or SMT solver as a symbolic node, a retrieval index as memory.

## Layout

```
synod/
  synod/
    protocol.py      message types (TaskView, Decline, Proposal, Verdict, Review, Record)
    learner.py       SparseLogLinear: the online learner behind the router and judge
    council.py       the learned council (router, reviewer routing, judge) and FixedPipeline, the baseline gate
    beliefs.py       Competence (hierarchical Beta), DriftMonitor
    objective.py     the one shared objective
    node.py          base Node: self-knowledge, learning, health
    nodes/           sequence world: intuition, recall, inducer, critic
    world.py, experiment.py, report.py      sequence world, runner, report
    maths/
      mathlang.py    reading notation: tokens, polynomials, equations, skeletons, task features
      programs.py    exact primitives, programs, search ("which program explains this answer?")
      nodes.py       parser, reader, estimator, checker
      world.py       the maths curriculum and its held-out test sets
      exam.py, trace.py, viewer.html          the 40-question exam and its step-by-step viewer
      experiment.py, report.py, __main__.py  train / ask / chat / report
    transcript.py    renders a deliberation as text
  tests/             35 tests (unittest)
  docs/ARCHITECTURE.md   the mechanics and the maths behind them
  results/           REPORT.md (sequences), MATHS_REPORT.md, EXAM_REPORT.md, council_viewer.html
```
