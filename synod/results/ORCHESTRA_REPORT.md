# The orchestra: one room for every modality

One room of 78 experts (every domain's operators, one neural pool, one memory, one analogy, one goal expert, every reviewer) and one judge. Arithmetic word problems, code from examples and algebra arrive mixed in one stream of practice, with nothing saying which is which; each domain's reader recognises its own problems, and everything else is learned together. Same practice per domain as the specialist rooms (8000 arithmetic, 3000 code, 2000 algebra). Averaged over 3 seeds.

## Right answers on every test set

| test set | the orchestra | range (orchestra) |
|---|---|---|
| algebra:compose | 0% | 0-0% |
| algebra:forms | 100% | 100-100% |
| algebra:longer | 6% | 5-6% |
| algebra:paraphrase | 78% | 77-79% |
| algebra:seen | 100% | 100-100% |
| arith:big | 100% | 99-100% |
| arith:compose | 20% | 11-35% |
| arith:distract | 15% | 11-20% |
| arith:longer | 4% | 0-11% |
| arith:missing | 61% | 48-84% |
| arith:paraphrase | 74% | 70-79% |
| arith:seen | 97% | 94-100% |
| arith:story | 60% | 49-82% |
| code:compose | 94% | 90-99% |
| code:longer | 24% | 19-33% |
| code:paraphrase | 97% | 93-99% |
| code:seen | 99% | 98-100% |

## Division of labour across modalities (seed 0)

Share of the steps in right test answers each kind of expert backed, per domain.

| domain | operator | neural | memory | analogy | goal |
|---|---|---|---|---|---|
| algebra | 79% | 100% | 71% | 19% | 21% |
| arith | 58% | 97% | 46% | 34% | 42% |
| code | 60% | 79% | 28% | 13% | 33% |

Where each neural expert's correct backing went (seed 0; entropy of 1.58 bits = spread evenly over the three, 0 = one modality only):

| expert | arithmetic | code | algebra | entropy (bits) |
|---|---|---|---|---|
| neural-1 | 32% | 20% | 48% | 1.49 |
| neural-2 | 32% | 20% | 48% | 1.50 |
| neural-3 | 29% | 21% | 50% | 1.49 |
| neural-4 | 39% | 28% | 33% | 1.57 |
| neural-5 | 29% | 21% | 50% | 1.49 |
| neural-6 | 33% | 19% | 48% | 1.49 |
| neural-7 | 32% | 18% | 50% | 1.47 |
| neural-8 | 33% | 20% | 47% | 1.51 |

Procedures kept: `(a + b) ÷ c`, `(a × b) ÷ 100`.

Wall-clock per run: 1090s.

