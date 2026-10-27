# Synod

**A council of neural and symbolic nodes that run themselves. There is no router.**

Synod is a working prototype of a neurosymbolic intelligence system where:

- there are many **nodes**, each either neural (learned, approximate, fast) or symbolic (explicit laws, exact, explainable);
- every node is responsible for the **efficiency and reliability of the whole system**, not just its own output;
- who does what is **not a programmed gate**. It comes out of the nodes' own learned self-knowledge, their trust in each other, and one shared objective;
- the symbolic nodes **learn and adapt** as well: they learn how to search, invent concepts, keep graded beliefs, and revise their rules.

It runs on Python + NumPy alone and finishes the full experiment in about a minute.

```bash
cd synod
python -m synod --seeds 5        # runs 8 strategies x 5 seeds, writes results/REPORT.md
python -m unittest discover -s tests -t .
```

---

## From the raw idea to mechanisms

| The idea | How Synod does it | Where |
|---|---|---|
| Many nodes, neural or symbolic | 4 nodes: `intuition` (MLP ensemble), `recall` (associative memory), `inducer` (program induction), `critic` (soft constraints). Add more by subclassing `Node`. | `synod/nodes/` |
| Each node optimizes efficiency **and** reliability of the whole | One shared `Objective` (+1 right, −1 wrong, 0 abstain, −0.02 per unit of compute). Every decision a node makes (look, bid, ask for review, learn, quarantine itself) is framed as "does this raise the system's expected utility?" | `objective.py`, `node.py` |
| Orchestrated to their strengths, not gated | Nodes bid their calibrated chance of success. The council ranks bids by expected utility, read through the **peers'** trust in the bidder. Nobody hard-codes "noisy → neural". | `council.py` |
| Autonomous interoperability | Leads **buy** reviews only when the information is worth the compute (value-of-information). Reviewers can **counter-propose**. Conflicting answers cast doubt on each other. Nodes **teach** each other through certified answers, **audit** each other, and **retract** lessons learned from a peer that broke. | `node.py`, `council.py` |
| Symbolic parts aren't dumb and stiff | The inducer learns per-situation search priors, invents concepts, knows when exact laws don't exist and switches to approximate laws, and explains every answer. The critic learns how far to trust each of its constraints. | `nodes/inducer.py`, `nodes/critic.py` |

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
                         │      reviewer endorses / rejects / counter-proposes
                         │            │
  candidates reconciled (two answers that can't both be right doubt each other)
                         │
         deliver if belief clears the bar, otherwise abstain honestly
                         │
  broadcast transcript ──► everyone updates self-models, trust, reviewer records
                       ──► learners absorb labels + certified answers (own bar)
                       ──► surprised / drifting nodes self-test, repair or quarantine
                       ──► peers file audit requests, retract tainted lessons
```

The council itself makes **no judgement calls**. It only runs the meeting.

## The nodes

| Node | Kind | Good at | Learns | Breaks and heals |
|---|---|---|---|---|
| `intuition` | neural (5-member MLP ensemble) | noisy, nonlinear series | labels + certified answers; puts its learning capacity where its own track record says it can help | weights corrupted → retrain from replay |
| `recall` | neural (associative memory, stand-in for an embedding store) | shapes it has seen, compiled from what the inducer taught it | stores labels + near-certain certified answers, with provenance | index corrupted → wipe and rebuild |
| `inducer` | symbolic (program induction over a grammar of laws) | exact laws: recurrences, polynomials, periodicities | search priors, concepts, where exact laws exist, which approximate laws work | can't fix its own code → quarantines itself until a hotfix passes its self-test |
| `critic` | symbolic (soft constraints) | cheap sanity checks | how often reality respects each constraint, per situation | — |

## What the symbolic side learned in one run

From `results/REPORT.md` (seed 0):

- It invented `x[n] = x[n-1] + x[n-2]` as a concept (confirmed 79×), along with `x[n] = 2*x[n-1]`, `x[n] = 3*x[n-1] + 1` and others, and checks them first, almost for free.
- It learned that in real-valued, loose-tolerance situations exact laws never turn up, so it stopped hunting for them there and switched to cheap approximate laws. Its compute on the noisy tasks it solved fell from 6.7 units (first 150 tasks) to 2.7 (after t=800).
- The critic learned "bounded-step" holds 100% of the time but "stays-in-envelope" only 73%, so it only vetoes on the former.

## Results

Scenario: 1600 "what comes next?" tasks from 9 hidden families. Exact-law families demand exact answers; noisy/nonlinear families only need to be close. Only 35% of tasks are ever labeled. Trouble is scheduled on purpose:

- **t=550** Recall's memory index is corrupted (it stays confident while wrong)
- **t=1000** a never-seen family appears
- **t=1250** a bug in the Inducer (+1 on every answer); **t=1400** an operator ships a hotfix

5 seeds, utility per task (higher is better):

| strategy | utility | accuracy | wrong | compute | right after memory fault | right after symbolic bug |
|---|---|---|---|---|---|---|
| **Synod** | **+0.675** | 81% | 8% | 2.43 | +0.68 (5% wrong) | **+0.40** |
| symbolic-only | +0.631 | 73% | 6% | 1.84 | +0.71 | −0.08 |
| hand-written gate | +0.522 | 63% | 9% | 1.08 | +0.50 | +0.01 |
| neural-only | +0.085 | 20% | 9% | 1.50 | +0.13 | +0.09 |
| Synod w/o review | +0.661 | 81% | 10% | 2.45 | +0.65 (12% wrong) | +0.35 |
| Synod w/o trust | +0.664 | 80% | 9% | 2.46 | +0.61 (10% wrong) | +0.35 |
| Synod w/o exchange | +0.646 | 78% | 9% | 2.47 | +0.57 | +0.26 |
| Synod w/o self-healing | +0.584 | 76% | 12% | 2.78 | +0.54 | −0.30 |

What this shows:

- **Emergent division of labour.** Without being told task families, Recall ended up owning arithmetic/geometric/affine (it memorised what the Inducer taught it, and those shapes repeat), the Inducer kept Fibonacci, quadratics and the new interleaved family, and Intuition took over waves and saturating curves.
- **Self-healing is the biggest single win.** In seed 0, Recall caught its own corruption 2 tasks after it happened, wiped its memory and rebuilt it. The Inducer was surprised by a 99%-confident miss 23 tasks after its bug appeared, failed its own regression test and quarantined itself. Peers retracted the lessons it had taught them, and it came back on probation after the hotfix. Without self-healing, that window collapses to 59% wrong answers.
- **Review and trust are insurance, not a tax.** In calm periods they're roughly break-even, since confident leads rightly skip review. Right after a fault they **halve the wrong-answer rate** (12% → 5%).
- **Knowledge exchange pays.** Certified answers let memory and intuition learn from the inducer (and give the system backup when it breaks).

Caveats:

- The bidding overhead is real. Synod uses more compute than the hand-written gate (2.4 vs 1.1 per task). The gate is cheaper but much less reliable, and the utility numbers include compute.
- In calm windows, symbolic-only is sometimes level with Synod. In this world the inducer is strong. Synod's lead comes from not breaking when parts break, and from covering what one paradigm can't.
- The world is synthetic and small. It was designed so both paradigms have real niches. That's the premise being tested, not a law of nature.

## A deliberation, verbatim

```text
task #633  [11, 14, 25, 39, 64, 103, 167, 270, ?]  tolerance ±0.5  (hidden family: fibonacci)
  intuition declines: rarely useful here (p_useful~0.00)
  recall    bids p=0.95 (calibrated 0.58), needs 0.0 more compute
  inducer   bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  -> recall leads: 436.50  conf 0.58  because recalls near match -> 436.50
     recall asks inducer for review -> REJECTS: law x[n] = x[n-1] + x[n-2] gives 437   (belief 0.66 -> 0.20)
     inducer counter-proposes 437 (conf 0.99)
  => delivers 437 from inducer (belief 0.59)  [truth 437: correct]  compute 0.6
```

The neural memory chose for itself to get a symbolic second opinion, got overruled by an exact law, and the council went with the law. More examples are in `results/REPORT.md`.

## Plugging in real nodes

A node is anything that implements five methods (see `synod/node.py`):

```python
class MyNode(Node):
    kind = NEURAL            # or SYMBOLIC
    def glance(self, view):  # cheap look -> (evidence tuple, compute spent, compute still needed)
    def solve(self, view):   # -> Proposal(value, confidence, cost, rationale, evidence)
    def critique(self, view, proposal):  # -> Verdict(endorses True/False/None, counter=...)
    def learn(self, view, value, source, record):  # absorb a label or certified answer
    def repair(self):        # try to fix yourself; return True if you did
```

Bidding, calibration, trust, review decisions, drift detection, audits, quarantine and probation all come from the base class. Natural next nodes: an LLM call as a neural node (`glance` = a cheap model, `solve` = a bigger one), a SAT/SMT solver or Prolog engine as a symbolic node, a retrieval index as memory. `TaskView`, `Proposal.value` and the tolerance check are where you'd generalise from numbers to your own task type.

## Layout

```
synod/
  synod/
    protocol.py      message types (TaskView, Bid, Proposal, Verdict, Review, Record)
    beliefs.py       Competence (hierarchical Beta), ClaimCalibrator (trust), DriftMonitor
    objective.py     the one shared objective
    perception.py    coarse task "shape" every node conditions on
    node.py          base Node: all the autonomous behaviour
    council.py       the protocol (and FixedPipeline, the baseline gate)
    nodes/           intuition, recall, inducer, critic
    world.py         the synthetic world, faults and shift
    experiment.py    strategies, ablations, runner
    report.py        builds results/REPORT.md
    transcript.py    renders a deliberation as text
  tests/             24 tests (unittest)
  docs/ARCHITECTURE.md   the mechanics and the maths
  results/REPORT.md      the latest full run
```
