# The orchestra: one room for every modality

One room of 77 experts (every domain's operators, one neural pool, one memory, one analogy, one goal expert, every reviewer) and one judge. Arithmetic word problems, code from examples and algebra arrive mixed in one stream of practice, with nothing saying which is which; each domain's reader recognises its own problems, and everything else is learned together. Same practice per domain as the specialist rooms (8000 arithmetic, 3000 code, 2000 algebra). Averaged over 3 seeds.

## Right answers on every test set

| test set | the orchestra | range (orchestra) |
|---|---|---|
| algebra:compose | 100% | 100-100% |
| algebra:forms | 100% | 100-100% |
| algebra:longer | 45% | 14-99% |
| algebra:paraphrase | 100% | 100-100% |
| algebra:seen | 100% | 100-100% |
| arith:big | 98% | 97-99% |
| arith:compose | 28% | 19-45% |
| arith:distract | 19% | 11-28% |
| arith:longer | 24% | 0-42% |
| arith:missing | 68% | 51-81% |
| arith:paraphrase | 82% | 78-85% |
| arith:seen | 98% | 96-99% |
| arith:story | 46% | 33-66% |
| code:compose | 100% | 99-100% |
| code:longer | 56% | 0-84% |
| code:paraphrase | 95% | 94-96% |
| code:seen | 100% | 100-100% |

## Division of labour across modalities (seed 0)

Share of the steps in right test answers each kind of expert backed, per domain.

| domain | operator | neural | memory | analogy | goal |
|---|---|---|---|---|---|
| algebra | 82% | 99% | 42% | 17% | 18% |
| arith | 64% | 96% | 35% | 39% | 35% |
| code | 58% | 71% | 21% | 8% | 30% |

Where each neural expert's correct backing went (seed 0; entropy of 1.58 bits = spread evenly over the three, 0 = one modality only):

| expert | arithmetic | code | algebra | entropy (bits) |
|---|---|---|---|---|
| neural-1 | 29% | 17% | 54% | 1.43 |
| neural-2 | 29% | 17% | 54% | 1.43 |
| neural-3 | 26% | 17% | 57% | 1.41 |
| neural-4 | 37% | 23% | 40% | 1.55 |
| neural-5 | 27% | 17% | 56% | 1.41 |
| neural-6 | 31% | 19% | 50% | 1.48 |
| neural-7 | 28% | 15% | 57% | 1.39 |
| neural-8 | 29% | 18% | 53% | 1.44 |

Procedures kept: `(a × b) ÷ 100`.

Wall-clock per run: 1925s.

