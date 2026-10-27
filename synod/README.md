# Synod

**A council of neural and symbolic nodes that run themselves. There is no router.**

Synod is a working prototype of a neurosymbolic intelligence system where:

- there are many **nodes**, each either neural (learned, approximate, fast) or symbolic (explicit, exact, explainable);
- every node is responsible for the **efficiency and reliability of the whole system**, not just its own output;
- who does what is **not a programmed gate**. It comes out of the nodes' own learned self-knowledge, their trust in each other, and one shared objective;
- the symbolic nodes **learn and adapt** too: they learn how to search, invent concepts, learn what words mean, and revise their beliefs.

The same council runs in two worlds:

1. **Sequences**: "what comes next?" tasks with faults and distribution shift injected on purpose. This world shows the self-organisation and self-healing.
2. **Maths**: the council learns what maths questions *mean* purely from answered examples, then answers new ones. That includes wordings, word problems and combinations it has never seen, and it **asks for help** when it's stuck.

Plain Python + NumPy, no other dependencies.

```bash
cd synod
python -m synod.maths train                 # learn maths (~1 min), test it, save the council
python -m synod.maths ask "Suppose 2*n + 6 = 20. What is n times 8?"
python -m synod.maths chat                  # ask questions interactively
python -m synod.maths report --seeds 3      # compare strategies -> results/MATHS_REPORT.md
python -m synod --seeds 5                   # the sequence world -> results/REPORT.md
python -m unittest discover -s tests -t .   # 35 tests
```

---

## From the raw idea to mechanisms

| The idea | How Synod does it | Where |
|---|---|---|
| Many nodes, neural or symbolic | Sequences: `intuition` (MLP ensemble), `recall` (associative memory), `inducer` (program induction), `critic` (soft constraints). Maths: `reader` (neural), `estimator` (neural number sense), `parser` (symbolic), `checker` (symbolic). | `synod/nodes/`, `synod/maths/nodes.py` |
| Each node optimizes efficiency **and** reliability of the whole | One shared `Objective` (+1 right, −1 wrong, 0 abstain, −0.02 per unit of compute). Every decision a node makes (look, bid, ask for review, learn, quarantine itself) is framed as "does this raise the system's expected utility?" | `objective.py`, `node.py` |
| Orchestrated to their strengths, not gated | Nodes bid their calibrated chance of success. The council ranks bids by expected utility, read through the **peers'** trust in the bidder. Nobody hard-codes "noisy → neural" or "equation → solver". | `council.py` |
| Autonomous interoperability | Leads **buy** reviews only when the information is worth the compute. Reviewers **counter-propose**. Conflicting answers are weighed against each other. Nodes **teach** each other, but only from consensus and never from their own guesses on new ground. They **audit** each other, **retract** lessons from a peer that broke, and the council **asks a teacher** when it can't settle a question. | `node.py`, `council.py` |
| Symbolic parts aren't dumb and stiff | The sequence inducer learns per-situation search priors, invents concepts, and knows when exact laws don't exist. The maths parser learns what words mean, reasons by analogy, and composes programs for combinations it has never seen. Critics learn how far to trust each of their own rules. | `nodes/inducer.py`, `maths/nodes.py` |

## How a task flows

```
 task ──► every node: "is it worth even looking?" (learned)        ─┐
          cheapest lookers go first; later ones skip if covered     │  open-outcry
          look ──► bid = calibrated P(success) + exploration        ─┘  auction
                         │
  council ranks bids by expected utility, as read by the *other* nodes' trust
                         │
  lead solves ──► lead decides: is a review worth its compute? (VOI)
                         │            │
                         │      reviewer endorses / rejects / counter-proposes,
                         │      saying how sure it is
                         │            │
  rival answers weighed (exclusive answers can't jointly exceed 100%)
                         │
         deliver if belief clears the bar, otherwise abstain honestly
         (and, if split or stuck, ask a teacher afterwards, within a budget)
                         │
  broadcast transcript ──► everyone updates self-models, trust, reviewer records
                       ──► nodes share explanations (e.g. "this program explains the answer")
                       ──► learners absorb labels + consensus answers (own bar)
                       ──► surprised / drifting nodes self-test, repair or quarantine
                       ──► peers file audit requests, retract tainted lessons
```

The council itself makes **no judgement calls**. It only runs the meeting.

---

# Part 1: sequences, self-organisation and self-healing

| Node | Kind | Good at | Learns | Breaks and heals |
|---|---|---|---|---|
| `intuition` | neural (5-member MLP ensemble) | noisy, nonlinear series | labels + consensus answers; spends its learning capacity where its own record says it can help | weights corrupted → retrain from replay |
| `recall` | neural (associative memory) | shapes it has seen, compiled from what the inducer taught it | stores labels + near-certain answers, with provenance | index corrupted → wipe and rebuild |
| `inducer` | symbolic (program induction over a grammar of laws) | exact laws: recurrences, polynomials, periodicities | search priors, concepts, where exact laws exist | can't fix its own code → quarantines itself until a hotfix passes its self-test |
| `critic` | symbolic (soft constraints) | cheap sanity checks | how often reality respects each constraint, per situation | — |

Scenario: 1600 tasks from 9 hidden families, only 35% ever labeled. At **t=550** Recall's memory is corrupted (it stays confident while wrong). At **t=1000** a never-seen family appears. At **t=1250** the Inducer gets a bug (+1 on every answer), and at **t=1400** a hotfix ships.

5 seeds, utility per task (higher is better):

| strategy | utility | accuracy | wrong | compute | right after memory fault | right after symbolic bug |
|---|---|---|---|---|---|---|
| **Synod** | **+0.671** | 81% | 8% | 2.50 | +0.64 (8% wrong) | **+0.41** |
| symbolic-only | +0.631 | 73% | 6% | 1.84 | +0.71 | −0.08 |
| hand-written gate | +0.522 | 63% | 9% | 1.08 | +0.50 | +0.01 |
| neural-only | +0.085 | 20% | 9% | 1.50 | +0.13 | +0.09 |
| Synod w/o review | +0.660 | 80% | 10% | 2.43 | +0.65 (12% wrong) | +0.32 |
| Synod w/o trust | +0.656 | 80% | 9% | 2.47 | +0.60 (10% wrong) | +0.35 |
| Synod w/o exchange | +0.648 | 79% | 9% | 2.51 | +0.53 (17% wrong) | +0.31 |
| Synod w/o self-healing | +0.551 | 72% | 11% | 2.84 | +0.49 (19% wrong) | −0.36 (57% wrong) |

- **Emergent division of labour.** Without being told task families, Recall ended up owning arithmetic, geometric and affine sequences (it memorised what the Inducer taught it). The Inducer kept Fibonacci, quadratics and the new family. Intuition took over waves and saturating curves.
- **Self-healing is the biggest single win.** In seed 0, Recall caught its own corruption 9 tasks in, wiped its memory and rebuilt it. The Inducer was surprised by a 99%-confident miss 27 tasks after its bug, failed its own regression test and quarantined itself. Peers retracted the lessons it had taught them, and it came back on probation after the hotfix.
- **Review, trust and exchange are insurance.** Near break-even in calm periods; right after a fault they cut wrong answers from 12–17% to 8%.
- **The symbolic side learns.** The Inducer promoted `x[n] = x[n-1] + x[n-2]` to a concept after 80 confirmations. It also learned that exact laws never turn up in noisy real-valued data and switched to cheap approximate laws there, so its compute on those tasks fell from 6.0 to 3.1.
- **Caveats.** Bidding overhead is real (2.5 compute/task vs the gate's 1.1; the utility numbers include it). In calm windows symbolic-only is sometimes level with Synod. Synod's lead comes from not breaking when parts break.

A deliberation, trimmed (neural overrules symbolic, correctly):

```text
task #1038  [10.33, 12.67, 22.52, 38.63, 55.72, 68.02, 72.79, 76.92, ?]  tolerance ±2.9  (hidden family: saturating)
  inducer   bids p=1.00 (calibrated 0.95), needs 0.0 more compute
  -> inducer leads: 93.85  conf 0.74  because ~x[n] = 2.77*x[n-1] - 3.27*x[n-2] + 1.75*x[n-3]  (best approximate law)
     inducer asks intuition for review -> REJECTS: independently got 78.10, 5.4x tolerance away   (belief 0.65 -> 0.14)
     intuition counter-proposes 78.1 (conf 0.74)
  => answers 78.1 from intuition (belief 0.79)  [truth 78.38: correct]
```

---

# Part 2: Synod does maths

**Nobody tells the system what any wording means.** It gets 4,000 practice questions in the style of DeepMind's Mathematics Dataset (half with the answer revealed afterwards), then is tested on 1,250 questions with **no answers at all**.

| Node | Kind | What it knows | What it learns |
|---|---|---|---|
| `parser` | symbolic | how to *read notation* (numbers, lists, polynomials, equations, `f(x)=…`) and 26 exact operations, in rational arithmetic. **No English.** | Searches for the program that reproduces each answer, keeps a version space per wording, and learns word → operation meanings. Answers unfamiliar wordings by **analogy** ("like that one, but 'times' instead of 'plus'") or by **composing** programs from word meanings. |
| `reader` | neural (3-net ensemble over word n-grams) | nothing | Wording → program, trained on what the parser discovers. Generalises to paraphrases, and knows when a combination of important words is new to it. Execution stays exact. |
| `estimator` | neural | nothing | Number sense: the rough size of an answer. Vetoes answers in the wrong ballpark; says "no feel" on unfamiliar questions. |
| `checker` | symbolic | back-substitution, whole-number and yes/no checks | How reliable each check is for each wording. |

### Results (3 seeds; % right, wrong in brackets, the rest are honest abstentions)

| strategy | familiar wording | new wording | numbers 100× bigger | word problems* | new combinations |
|---|---|---|---|---|---|
| Synod | 100% (0%) | 75% (7%) | 99% (0%) | 63% (7%) | 10% (39%) |
| parser alone (symbolic) | 100% (0%) | 69% (4%) | 99% (0%) | 73% (0%) | 51% (0%) |
| reader alone (neural) | 97% (0%) | 82% (10%) | 97% (0%) | 58% (12%) | 1% (83%) |
| hand-written gate | 99% (0%) | 66% (10%) | 99% (0%) | 52% (4%) | 1% (91%) |
| **Synod + teacher** (asks ~36 of 1,250) | **100% (0%)** | **81% (6%)** | **100% (0%)** | **96% (0%)** | **87% (11%)** |

\* new names, new objects and new phrasings.

What this shows:

- **Exact symbolic execution doesn't care how big the numbers are**: 99–100% on numbers far outside training, where neural answering would fall over.
- **When it's stuck, it asks, and one answer generalises.** Letting the council ask a teacher about questions it couldn't settle (only ~3% of the test, chosen by the council itself) takes new combinations from 10% to **87%** and word problems from 63% to **96%**. It asks *after* answering, so it learns for next time, and it stops asking once a wording is learned.
- **The frontier (honest finding).** Without a teacher, on genuinely new combinations, the council does *worse* than its own Parser alone (10% vs 51%, and 39% wrong vs 0%). The Reader is confidently wrong there, and its self-assessment comes from training-time novelty, which was easier. Self-knowledge earned on familiar ground doesn't transfer to a harder regime without feedback. That's the most interesting thing to crack next.

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
What is the gcd of 84 and 126?                               -> abstains (never taught "gcd")
Calculate 15% of 80.                                         -> abstains (percent wasn't in the curriculum)
What is the capital of France?                               -> abstains (both nodes decline)
```

A deliberation (trimmed):

```text
Q: Zara has 12 mangoes and buys 9 more. How many mangoes does Zara have?
  parser    bids p=0.95 (calibrated 0.72)
  reader    bids p=1.00 (calibrated 1.00)
  -> parser leads: 21  conf 0.72  because (n1 + n2)  [like 'grace has # pencils grace gets # more how many
                                   pencils does grace have now' (0.26); cues: 'more'->add]
     parser asks checker for review -> endorses: passes whole-number   (belief 0.77 -> 0.83)
     parser asks estimator for review -> abstains: never seen questions like this; no feel for the size
  => answers 21 from parser (belief 0.83)
```

### What the parser learned words mean (from answers alone)

`remainder, modulo → mod` · `derivative, differentiate → slope` · `root → sqrt` · `mean, average → mean` · `greatest, divisor, factor → gcd` · `multiple, least, smallest → lcm` · `away, gives, left → subtract` · `times, multiplied → multiply` · `power, raised → pow` · `suppose → solve` · `next, comes, sequence → next term`

…plus some spurious ones that show it's statistics, not magic: `friends → divide` (from "shared equally between friends"), `box → add`, `a → is_prime` (from "Is # a prime number?").

---

## Plugging in real nodes

A node is anything that implements a few methods (see `synod/node.py`):

```python
class MyNode(Node):
    kind = NEURAL            # or SYMBOLIC
    def glance(self, view):  # cheap look -> (evidence tuple, compute spent, compute still needed)
    def solve(self, view):   # -> Proposal(value, confidence, cost, rationale, evidence, program)
    def critique(self, view, proposal):  # -> Verdict(endorses True/False/None, counter=..., evidence=...)
    def learn(self, view, value, source, record):  # absorb a label or a consensus answer
    def explain(self, record):  # optional: share an explanation with the others
    def repair(self):        # try to fix yourself; return True if you did
```

Bidding, calibration, trust, review decisions, conflict handling, drift detection, audits, quarantine and probation all come from the base class. Natural next nodes: an LLM call as a neural reader, a real CAS or SMT solver as a symbolic node, a retrieval index as memory.

## Layout

```
synod/
  synod/
    protocol.py      message types (TaskView, Bid, Proposal, Verdict, Review, Record)
    beliefs.py       Competence (hierarchical Beta), ClaimCalibrator (trust), DriftMonitor
    objective.py     the one shared objective
    node.py          base Node: all the autonomous behaviour
    council.py       the protocol (and FixedPipeline, the baseline gate)
    nodes/           sequence world: intuition, recall, inducer, critic
    world.py, experiment.py, report.py      sequence world, runner, report
    maths/
      mathlang.py    reading notation: tokens, polynomials, equations, skeletons
      programs.py    exact primitives, programs, search ("which program explains this answer?")
      nodes.py       parser, reader, estimator, checker
      world.py       the maths curriculum and its held-out test sets
      experiment.py, report.py, __main__.py  train / ask / chat / report
    transcript.py    renders a deliberation as text
  tests/             35 tests (unittest)
  docs/ARCHITECTURE.md   the mechanics and the maths behind them
  results/           REPORT.md (sequences), MATHS_REPORT.md (maths)
```
