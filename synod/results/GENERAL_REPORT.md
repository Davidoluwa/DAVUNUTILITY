# The room on other modalities

One engine. Each domain supplies only a reader, its operations and its check; the experts, the judge, deliberation, search, learning, sleep and invention are the same code that does arithmetic word problems (`results/ROOM_REPORT.md`). Averaged over 3 seeds; range across seeds in brackets.

## code

Write a list program from a description and three examples. No answers are ever revealed: the examples are the only check, and the room delivers only a program that passes them. Graded on four hidden inputs of other lengths and ranges. When nothing passes, the room searches, then searches twice as wide, and again (6, 12, 24 routes), and as a last resort once more trusting its own judge less (doubt after failure).

| strategy | seen | paraphrase | compose | longer |
|---|---|---|---|---|
| the room | 99% (98%-100%) | 95% (88%-100%) | 100% (99%-100%) | 43% (34%-48%) |
| operators alone (no neural, memory or analogy) | 100% (99%-100%) | 96% (95%-98%) | 92% (87%-100%) | 25% (7%-37%) |
| search alone, nothing learned | 91% (90%-92%) | 92% (91%-95%) | 81% (74%-85%) | 0% (0%-0%) |

Wrong answers (the rest of the misses are abstentions):

| strategy | seen | paraphrase | compose | longer |
|---|---|---|---|---|
| the room | 0% | 1% | 0% | 10% |
| operators alone (no neural, memory or analogy) | 0% | 0% | 1% | 8% |
| search alone, nothing learned | 4% | 3% | 7% | 0% |

Compute per question (units of expert work, including any search):

| strategy | seen | paraphrase | compose | longer |
|---|---|---|---|---|
| the room | 47 | 116 | 56 | 1156 |
| operators alone (no neural, memory or analogy) | 11 | 80 | 89 | 786 |
| search alone, nothing learned | 170 | 169 | 308 | 1362 |

- **seen**: familiar kinds of task
- **paraphrase**: descriptions worded in new ways
- **compose**: combinations of steps never seen together
- **longer**: four-step programs (training had at most three)

Procedures the room tried: none. Kept: none.

Wall-clock per run (practice and tests, one core): 186s.

## algebra

Solve equations and systems of equations by general moves (expand, gather terms, divide both sides, isolate, substitute, eliminate, read off a value); no solve move. Half the practice questions reveal their answer, never the derivation. When unsure, the room deliberates again with a wider beam and more options per operator.

| strategy | seen | paraphrase | forms | compose | longer |
|---|---|---|---|---|---|
| the room | 100% (100%-100%) | 99% (96%-100%) | 100% (100%-100%) | 100% (100%-100%) | 11% (6%-13%) |
| operators alone (no neural, memory or analogy) | 100% (100%-100%) | 78% (77%-80%) | 100% (100%-100%) | 0% (0%-0%) | 12% (10%-14%) |
| search alone, nothing learned | 0% (0%-0%) | 0% (0%-0%) | 0% (0%-0%) | 0% (0%-0%) | 0% (0%-0%) |

Wrong answers (the rest of the misses are abstentions):

| strategy | seen | paraphrase | forms | compose | longer |
|---|---|---|---|---|---|
| the room | 0% | 1% | 0% | 0% | 13% |
| operators alone (no neural, memory or analogy) | 0% | 22% | 0% | 0% | 11% |
| search alone, nothing learned | 0% | 0% | 0% | 0% | 0% |

Compute per question (units of expert work, including any search):

| strategy | seen | paraphrase | forms | compose | longer |
|---|---|---|---|---|---|
| the room | 53 | 53 | 50 | 46 | 223 |
| operators alone (no neural, memory or analogy) | 22 | 14 | 9 | 88 | 65 |
| search alone, nothing learned | 311 | 308 | 259 | 316 | 318 |

- **seen**: familiar kinds of question
- **paraphrase**: questions worded in new ways
- **forms**: equation shapes and variable letters never seen
- **compose**: systems needing moves never combined in training
- **longer**: three equations in three unknowns (training had at most two)

Procedures the room tried: `value(divide(eliminate(a, b, c)))`. Kept: none.

Wall-clock per run (practice and tests, one core): 181s.

