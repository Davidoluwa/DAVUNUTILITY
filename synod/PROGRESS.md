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

## 3. Algebra (in progress): full derivations

Equations and systems of equations, solved through general algebraic moves (expand, gather terms, divide both sides, isolate, substitute, eliminate), never a "solve" button. Every line of the derivation is shown.

## 4. Evaluation across all three, docs (to do)
