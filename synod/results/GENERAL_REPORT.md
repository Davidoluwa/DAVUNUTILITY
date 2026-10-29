# The room on other modalities

One engine. Each domain supplies only a reader, its operations and its check; the experts, the judge, deliberation, search, learning, sleep and invention are the same code that does arithmetic word problems (`results/ROOM_REPORT.md`). Averaged over 3 seeds; range across seeds in brackets.

## code

Write a list program from a description and three examples. No answers are ever revealed: the examples are the only check, and the room delivers only a program that passes them. Graded on four hidden inputs of other lengths and ranges. When nothing passes, the room searches, then searches twice as wide, and again (6, 12, 24 routes), then once more trusting its own judge less (doubt after failure), and last without the experts that propose by habit (neural pool, memory, analogy).

| strategy | seen | paraphrase | compose | longer |
|---|---|---|---|---|
| the room | 100% (100%-100%) | 93% (91%-95%) | 99% (98%-100%) | 81% (70%-87%) |
| operators alone (no neural, memory or analogy) | 99% (98%-100%) | 95% (89%-98%) | 99% (99%-100%) | 79% (64%-87%) |
| search alone, nothing learned | 91% (90%-92%) | 92% (91%-95%) | 81% (74%-85%) | 0% (0%-0%) |

Wrong answers (the rest of the misses are abstentions):

| strategy | seen | paraphrase | compose | longer |
|---|---|---|---|---|
| the room | 0% | 1% | 1% | 7% |
| operators alone (no neural, memory or analogy) | 0% | 1% | 1% | 9% |
| search alone, nothing learned | 4% | 3% | 7% | 0% |

Compute per question (units of expert work, including any search):

| strategy | seen | paraphrase | compose | longer |
|---|---|---|---|---|
| the room | 43 | 176 | 58 | 837 |
| operators alone (no neural, memory or analogy) | 23 | 109 | 19 | 438 |
| search alone, nothing learned | 183 | 183 | 341 | 1661 |

- **seen**: familiar kinds of task
- **paraphrase**: descriptions worded in new ways
- **compose**: combinations of steps never seen together
- **longer**: four-step programs (training had at most three)

Procedures the room tried: none. Kept: none.

Wall-clock per run (practice and tests, one core): 779s.

## algebra

Solve equations and systems of equations by general moves (expand, gather terms, divide both sides, isolate, substitute, eliminate, read off a value); no solve move. Half the practice questions reveal their answer, never the derivation. When unsure, the room deliberates again with a wider beam and more options per operator. Answering for real, an answer that doesn't come with a derivation of the asked variables is a guess; unsure or guessing, the room searches for such a derivation (every move is sound, so it is a proof) and finishes from there.

| strategy | seen | paraphrase | forms | compose | longer |
|---|---|---|---|---|---|
| the room | 100% (100%-100%) | 100% (100%-100%) | 100% (100%-100%) | 100% (100%-100%) | 49% (21%-100%) |
| operators alone (no neural, memory or analogy) | 100% (100%-100%) | 78% (77%-80%) | 100% (100%-100%) | 100% (100%-100%) | 19% (16%-21%) |
| search alone, nothing learned | 0% (0%-0%) | 0% (0%-0%) | 0% (0%-0%) | 0% (0%-0%) | 0% (0%-0%) |

Wrong answers (the rest of the misses are abstentions):

| strategy | seen | paraphrase | forms | compose | longer |
|---|---|---|---|---|---|
| the room | 0% | 0% | 0% | 0% | 0% |
| operators alone (no neural, memory or analogy) | 0% | 22% | 0% | 0% | 0% |
| search alone, nothing learned | 0% | 0% | 0% | 0% | 0% |

Compute per question (units of expert work, including any search):

| strategy | seen | paraphrase | forms | compose | longer |
|---|---|---|---|---|---|
| the room | 54 | 58 | 45 | 50 | 1314 |
| operators alone (no neural, memory or analogy) | 9 | 17 | 8 | 24 | 501 |
| search alone, nothing learned | 822 | 783 | 336 | 1470 | 1726 |

- **seen**: familiar kinds of question
- **paraphrase**: questions worded in new ways
- **forms**: equation shapes and variable letters never seen
- **compose**: systems needing moves never combined in training
- **longer**: three equations in three unknowns (training had at most two)

Procedures the room tried: `value(divide(eliminate(a, b, c)))`. Kept: none.

Wall-clock per run (practice and tests, one core): 1615s.

