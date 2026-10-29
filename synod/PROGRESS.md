# Overnight progress: from a maths room to a general one

Goal for the night: make the room a general system. That means one engine, with each modality supplying as little handwritten code as possible; full solutions to harder maths, worked out from the problem itself; and proof that it generalises.

## 1. One engine, many domains (done)

The room's machinery no longer knows it's doing arithmetic. That covers the experts, the judge, deliberation, the search for worked solutions, learning, sleep and invention. A **Domain** supplies only:

- a reader (problem text → facts);
- its operations (signature, result kind, how to run one, how to say it);
- constants that are always on the table;
- when two results match, and how to grade an answer;
- optionally, its own reviewers and a fallback search.

Arithmetic is the first domain. Its behaviour is **byte-identical** to before the change: a fingerprint of every answer and probability over 1800 practice and 120 test questions matched.

**Verifiable domains:** some problems carry their own check, such as examples a program must pass. In those domains the room delivers only answers that pass the check, and it learns from them **with no teacher and no revealed answers**. When nothing passes, it **thinks harder by itself**: it searches, then searches again twice as wide (6 → 12 → 24), stopping as soon as something passes.

## 2. Code (done): write a program from a description and examples

```text
Q: Keep the 3 largest numbers, biggest first. Examples: [5, 1, 4, 9, 2] -> [9, 5, 4]; [3, 8, 1, 7] -> [8, 7, 3]

def solve(xs):
    s1 = sorted(xs, reverse=True)
    s2 = s1[:3]
    return s2
```

**What the domain supplies:** a reader for "description + examples", and 26 list operations, each with its Python form. That's all. The rest (which operations to use, in what order, on what, guided by which words) is learned by the same experts and judge as in arithmetic.

**Grading:** every answer is graded on **hidden inputs** of other lengths and ranges, so a program that only fits the examples fails.

Results after 3,000 practice tasks (seed 0; no answers ever revealed, the examples are the only check):

| test set | the room | operators alone | search with nothing learned |
|---|---|---|---|
| familiar kinds of task | 100% | 95% | 90% |
| descriptions worded in new ways | 96% | 96% | 91% |
| combinations never seen together | 99% | 100% | 85% |
| four-step programs (training had at most three) | **46%** | 5% | **0%** |

- **Learning is what reaches depth.** At the same search budget, the learned room solves 22% / 35% / 48% of four-step programs at search widths 6 / 12 / 24. Search with nothing learned solves 0% at every width up to 48.
- **By the end of practice it solves every training task by deliberation alone**, with no search.
- **Where it still fails:** on new four-step combinations it trusts the familiar three-step frame. For "the 2 largest *different* numbers" it skips "remove duplicates", although the word reviewer flags "different" as unexplained. Searching wider rescues about half of these.

## 3. Algebra (done): full derivations from the problem

```text
Q: Given -6x - 4y = -42 and 5(5x - 2y) = 175, what is x plus y?
  Step 1: expand 5(5x - 2y) = 175:   25x - 10y = 175
  Step 2: eliminate y from -6x - 4y = -42 and 25x - 10y = 175:   160x = 1120
  Step 3: divide both sides of 160x = 1120:   x = 7
  Step 4: so the value is 7
  Step 5: eliminate x from -6x - 4y = -42 and 25x - 10y = 175:   -160y = 0
  Step 6: divide both sides of -160y = 0:   y = 0
  Step 7: so the value is 0
  Step 8: 7 + 0 = 7          => 7   [correct]
```

That derivation comes from a test set of systems that need multiplying out first. That **combination** of moves never appeared in training.

**What the domain supplies:**
- an exact linear-algebra core;
- a parser for equations as written;
- seven general moves: expand, gather terms, divide both sides, isolate, substitute, eliminate, read off a value;
- a glance at each equation's shape (raw, gathered, isolated, solved, whether it's about what the question asks).

There is **no solve move**. Which moves to make, in what order, on what, is learned, from answers alone (half of the practice questions reveal the number, never the derivation).

Results after 2,000 practice questions (seed 0):

| test set | right |
|---|---|
| familiar kinds of question | 100% |
| questions worded in new ways | 100% |
| **equation shapes never seen** (brackets on both sides, two brackets on one side), **with variable letters never seen** (m, n, p, …) | 100% |
| **systems that need multiplying out first** (moves seen, never together) | 100% |
| **three equations in three unknowns** (training had at most two) | 7% (10% wrong, the rest abstained) |

- **The frontier is three-equation systems.** The room has never seen a three-variable equation, so "eliminate removes one variable" was never observable to it. Without a handwritten strategy it derives true facts (e.g. z = 3), but rarely the asked one. Thinking harder (a wider beam, more options per operator) moved this from 0% to 7%.
- **Invention found the 2×2 lemma by itself:** `value(divide(eliminate(a, b, c)))`, i.e. eliminate, divide, read off. It was tried and dropped, because the copy never needed it on the trial's questions.

## 4. Three seeds each, against baselines (done)

| code | familiar | new wording | new combinations | four steps |
|---|---|---|---|---|
| the room | 99% | 95% | 100% | **43%** (34–48%) |
| operators alone | 100% | 96% | 92% | 25% |
| search with nothing learned | 91% | 92% | 81% | 0% |

The last change that mattered: when even the widest search fails the examples, the room searches once more **trusting its own judge less** (doubt after failure). Four-step programs went from 20% (4–46% across seeds) to 43% (34–48%).

| algebra | familiar | new wording | new shapes and letters | moves never combined | three equations |
|---|---|---|---|---|---|
| the room | 100% | 99% | 100% | **100%** | 11% |
| operators alone | 100% | 78% | 100% | **0%** | 12% |
| search with nothing learned | 0% | 0% | 0% | 0% | 0% |

## 5. The orchestra: one room for every modality (done)

**One population, one judge:** 78 experts and one judge.

**One stream:** arithmetic, code and algebra arrive mixed in one stream of practice, with nothing saying which is which. Each domain's reader recognises its own problems.

**Shared tools:** operators bind whatever is on the table, so algebra can borrow arithmetic's `is_prime`.

| | the orchestra | the specialists |
|---|---|---|
| arithmetic: familiar / ×100 / word problems | 97 / 100 / 60 | 95 / 98 / 54 |
| arithmetic: new combinations / missing info | 20 / 61 | 33 / 78 |
| code: familiar / wording / combinations / four steps | 99 / 97 / 94 / 24 | 99 / 95 / 100 / 43 |
| algebra: familiar / new shapes | 100 / 100 | 100 / 100 |
| algebra: new wording / moves never combined | 78 / **0** | 99 / **100** |

It holds together and kept two invented procedures. Sharing has a cost, though. At depth it's weaker than the specialists (four-step code 24% vs 43%), and on algebra's unseen combinations the orchestra **derives the right answer and abstains**. The shared judge trusts the necessary first move (expanding the brackets) too little, so the route's probability stays under the answer bar. No modality specialisation emerged among the neural experts.

## Honest summary

**What works:**
- One engine, three modalities, little domain code.
- Learning from examples alone (code) and from answers alone (algebra).
- Full derivations.
- New wordings, new shapes and new combinations at or near 100% in code and algebra.
- The room thinks harder by itself when its check fails.

**What doesn't yet:**
- **Depth.** Every modality struggles one step past its training: code 43%, algebra 11%, arithmetic ≤ 10%.
- **Specialisation.** The shared population didn't divide work across modalities.
- **Calibration under sharing.** See algebra above.

**Next:** state analogy (treat a derived configuration as a familiar problem), adopting invented lemmas, and hard routing.
