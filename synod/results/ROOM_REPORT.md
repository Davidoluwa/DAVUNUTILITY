# The room: a large council that solves maths step by step

43 experts in the room at the start (seed 0 ended with 43, after inventing 0 procedures). The curriculum has 75 kinds of question needing one to four steps; a quarter of the word problems carry a sentence that doesn't matter, and some questions leave out a number they need. 8000 practice questions, half with the answer revealed afterwards (never the method); then eight test sets with no answers at all. The room is frozen for testing.

Averaged over 3 seeds (range across seeds below).

## Right answers on each test set (wrong in brackets; the rest are abstentions)

| strategy | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| room | 96% (3%) | 75% (14%) | 96% (3%) | 53% (22%) | 34% (47%) | 9% (60%) | 21% (28%) | 72% (4%) |
| room, without inventing procedures | 96% (3%) | 77% (15%) | 96% (3%) | 58% (25%) | 50% (31%) | 17% (46%) | 26% (32%) | 79% (7%) |
| room, one neural expert | 96% (2%) | 74% (21%) | 98% (2%) | 54% (14%) | 43% (40%) | 12% (61%) | 20% (26%) | 66% (11%) |
| operators alone (no neural, memory or analogy) | 93% (2%) | 72% (3%) | 92% (2%) | 46% (8%) | 59% (7%) | 0% (1%) | 4% (8%) | 39% (0%) |
| search alone, no learning | 0% (0%) | 0% (0%) | 0% (0%) | 0% (0%) | 0% (0%) | 0% (0%) | 0% (0%) | 0% (0%) |
| council v2 (question -> answer) | 89% (0%) | 41% (4%) | 96% (0%) | 64% (12%) | 0% (22%) | 0% (35%) | 16% (29%) | 0% (49%) |

- **seen**: familiar wording, new numbers
- **paraphrase**: wording never seen in training
- **big**: numbers ~100x bigger than training
- **story**: word problems (1-3 steps): new names, objects and phrasings
- **compose**: combinations of familiar steps never seen together (2-3 steps)
- **longer**: four-step problems, longer than anything in training
- **distract**: word problems with one or two sentences that don't matter (new ones, some with numbers, some vague)
- **missing**: word problems missing a number they need ("buys some packs"): the right outcome is "not enough information"; kinds of question never seen incomplete in training

Spread across seeds (lowest-highest accuracy):

| strategy | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| room | 94%-100% | 67%-82% | 94%-98% | 49%-56% | 10%-50% | 0%-26% | 10%-28% | 53%-83% |
| room, without inventing procedures | 94%-97% | 66%-86% | 96%-97% | 50%-65% | 47%-53% | 0%-52% | 20%-32% | 77%-84% |
| room, one neural expert | 93%-98% | 72%-76% | 96%-98% | 50%-62% | 40%-46% | 0%-36% | 10%-32% | 48%-80% |
| operators alone (no neural, memory or analogy) | 92%-93% | 68%-75% | 91%-94% | 38%-56% | 52%-64% | 0%-0% | 2%-7% | 35%-46% |

## Relevance and missing information

How often each room said "not enough information". On the missing set that's the right answer; anywhere else it's a false alarm (and counted as wrong above).

| strategy | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| room | 0% | 0% | 0% | 0% | 0% | 0% | 2% | 72% |
| room, without inventing procedures | 0% | 0% | 0% | 0% | 0% | 0% | 2% | 79% |
| room, one neural expert | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 66% |
| operators alone (no neural, memory or analogy) | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 39% |

## Inventing procedures

Every 1000 practice questions the room sleeps on 300 of its past worked solutions. If its notebook shows a recurring piece, a copy of the room adopts it as a new operation (with its own expert) and sleeps on the same solutions re-expressed with it. Both then meet the next 500 questions before learning from them. The copy replaces the room only if it was less surprised by the worked solutions (total -log probability, in nats), used the procedure, and lost no more answers than it won.

Seed 0:

| at question | procedure | seen in notebook | surprise: room / copy | answers won-lost | copy used it | kept |
|---|---|---|---|---|---|---|
| 1500 | `a − (b × c)` | 26x in 25 wordings | 150.6 / 168.1 | 0-0 | 6 | dropped |
| 3000 | `a + (b × c)` | 70x in 59 wordings | 106.4 / 97.4 | 0-2 | 6 | dropped |
| 4500 | `(a + b) − c` | 103x in 93 wordings | 105.0 / 112.8 | 0-0 | 12 | dropped |
| 6000 | `(a + b) ÷ c` | 108x in 52 wordings | 58.1 / 60.5 | 0-1 | 6 | dropped |
| 7500 | `(a + (b × c)) − d` | 58x in 46 wordings | 52.3 / 128.3 | 0-1 | 10 | dropped |

Seed 1:

| at question | procedure | seen in notebook | surprise: room / copy | answers won-lost | copy used it | kept |
|---|---|---|---|---|---|---|
| 1500 | `a + (b × c)` | 32x in 29 wordings | 71.2 / 93.6 | 0-1 | 10 | dropped |
| 3000 | `(a + b) − c` | 63x in 57 wordings | 68.8 / 73.9 | 0-0 | 5 | dropped |
| 4500 | `(a + (b × c)) − d` | 42x in 36 wordings | 44.9 / 55.9 | 0-2 | 3 | dropped |
| 6000 | `(a + b) ÷ c` | 112x in 42 wordings | 12.6 / 16.8 | 0-0 | 12 | dropped |
| 7500 | `a − (b × c)` | 100x in 78 wordings | 23.8 / 23.9 | 0-0 | 4 | dropped |

Seed 2:

| at question | procedure | seen in notebook | surprise: room / copy | answers won-lost | copy used it | kept |
|---|---|---|---|---|---|---|
| 1500 | `(a + b) ÷ c` | 39x in 21 wordings | 286.2 / 346.1 | 0-1 | 7 | dropped |
| 3000 | `(a + b) − c` | 76x in 71 wordings | 130.7 / 168.6 | 0-1 | 5 | dropped |
| 4500 | `a + (b × c)` | 91x in 80 wordings | 44.5 / 58.6 | 0-0 | 8 | dropped |
| 6000 | `(a + (b × c)) − d` | 65x in 54 wordings | 91.0 / 119.2 | 0-1 | 4 | dropped |
| 7500 | `a − (b × c)` | 105x in 89 wordings | 58.1 / 61.9 | 0-0 | 3 | dropped |

Share of right test answers that used an invented procedure (mean over seeds):

| | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| room | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 0% |

Useful invention: the room minus the same room that never invents (right answers, same beam):

| | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| difference | +0 | -2 | -0 | -6 | -16 | -9 | -5 | -8 |

## Right for the right reason

Of the right answers, how many used the same method as the hidden reference program (commutative arguments aside; invented procedures written out)? On the distract set that means it left the sentences that don't matter alone.

| strategy | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| room | 93% | 96% | 93% | 100% | 97% | 67% | 88% | 100% |
| room, without inventing procedures | 92% | 97% | 93% | 100% | 97% | 14% | 95% | 100% |
| room, one neural expert | 92% | 95% | 94% | 100% | 100% | 33% | 96% | 100% |
| operators alone (no neural, memory or analogy) | 98% | 97% | 96% | 100% | 100% | 0% | 100% | 100% |

## Division of labour (seed 0)

Share of the steps in right test solutions that each kind of expert backed (a step can have several backers).

| test set | operator | neural | memory | analogy | goal |
|---|---|---|---|---|---|
| seen | 59% | 100% | 97% | 3% | 40% |
| paraphrase | 52% | 95% | 0% | 95% | 48% |
| big | 50% | 99% | 100% | 0% | 49% |
| story | 53% | 100% | 0% | 90% | 47% |
| compose | 69% | 93% | 0% | 38% | 31% |
| longer | 0% | 0% | 0% | 0% | 0% |
| distract | 65% | 100% | 0% | 35% | 35% |
| missing | 60% | 100% | 0% | 21% | 40% |

The neural pool is trained as a mixture of experts: each worked step is shared out in proportion to how well each network already predicts it. Where each network's correct backing concentrates (seed 0):

| expert | most backed kind of question | share | entropy (bits) |
|---|---|---|---|
| neural-1 | story_change | 4% | 5.77 |
| neural-2 | story_gain_lose | 4% | 5.78 |
| neural-3 | story_change | 5% | 5.75 |
| neural-4 | story_sub | 4% | 5.85 |
| neural-5 | story_gain_lose | 5% | 5.74 |
| neural-6 | story_gain_lose | 4% | 5.77 |
| neural-7 | story_gain_lose | 4% | 5.76 |
| neural-8 | story_gain_lose | 4% | 5.80 |

## The 40-question exam

The hand-written exam from `maths/exam.py` (new numbers, 18 new wordings), now answered step by step.

| | right | wrong | abstained |
|---|---|---|---|
| room | 33 | 7 | 0 |
| council v2 (question -> answer) | 27 | 0 | 13 |

Training accuracy per 1000 questions (room, seed 0): 54%, 86%, 90%, 93%, 95%, 96%, 97%, 96%

Seed 0: {'searched': 378, 'found': 338, 'own_solution': 3612, 'certified': 3308, 'told_insufficient': 3}

Wall-clock per run (practice + all test sets, one core each, four at a time): room 1137s, room, without inventing procedures 926s, room, one neural expert 991s, operators alone (no neural, memory or analogy) 401s, search alone, no learning 146s, council v2 (question -> answer) 436s

## Sample deliberations (seed 0, auto-picked)

### A three-step word problem, every expert in its lane

```text
Q: Kofi collected 12 stamps, was given 16 more, then gave 11 away. How many stamps does Kofi have left?  (hidden type: story_gain_lose)
  on the table: N1 = 12, N2 = 16, N3 = 11
  Step 1: 12 + 16 = 28
      add(N1,N2)   judge 0.94   backed by neural-1 0.48, add 0.45, neural-4 0.38, neural-3 0.35 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi, relevance uses:hi
      why: +1.0 v|lexicon:explains:hi, −0.7 by|analogy|analogy/sim0, +0.6 by|neural-5|n/c5
      also on the table: none of these 0.05
  Step 2: 28 − 11 = 17
      sub(S1,N3)   judge 1.00   backed by neural-1 0.99, neural-6 0.99, neural-5 0.96, neural-3 0.94 +4 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi, relevance uses:hi
      why: +1.8 conf:max, +1.0 v|lexicon:explains:hi, +0.9 conf:mean
  Done: the answer is 17
      answer   judge 1.00   backed by goal 0.99, neural-1 0.98, neural-6 0.96, neural-5 0.96 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:0, relevance open-relevant:0, relevance open-max:lo
      why: +1.8 conf:max, +1.2 by|goal|done/c5, +0.9 conf:mean
  => 17   probability 0.94 (2 routes reached it)  [truth 17: correct]   compute 64.3
     other answers considered: 5 (0.00, 1 route), not enough information (0.00, 5 routes)
```

### A combination never seen in training

```text
Q: Suppose 4*x + 15 = x + 48. What is x squared minus 7?  (hidden type: solve_sq_sub)
  on the table: N1 = 7, Q1 = 4*x + 15 = x + 48
  Step 1: solve 4*x + 15 = x + 48 for x: x = 11
      solve(Q1)   judge 1.00   backed by solve 0.99, neural-1 0.99, neural-6 0.99, neural-7 0.97 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:weak, lexicon explains:hi
      why: +1.8 conf:max, +1.3 conf:mean, +1.0 v|lexicon:explains:hi
  Step 2: 11² = 121
      square(S1)   judge 1.00   backed by neural-1 0.99, neural-6 0.99, neural-7 0.97, neural-5 0.96 +2 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:weak, lexicon explains:hi
      why: +1.8 conf:max, +1.3 conf:mean, +1.0 v|lexicon:explains:hi
  Step 3: 121 − 7 = 114
      sub(S2,N1)   judge 0.67   backed by sub 0.80
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:weak, lexicon explains:hi, relevance uses:hi
      why: +1.0 v|lexicon:explains:hi, +0.6 uses-last|1, +0.6 conf:max
      also on the table: add(N1,S2) 0.20 (add+2), answer 0.06 (neural-1+7), none of these 0.06
  Done: the answer is 114
      answer   judge 1.00   backed by goal 0.99, neural-1 0.98, neural-6 0.96, neural-5 0.96 +5 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:weak, estimator size:close, lexicon unexplained:0, relevance open-relevant:0, relevance open-max:lo
      why: +1.8 conf:max, +1.2 by|goal|done/c5, +1.0 conf:mean
  => 114   probability 0.67 (1 route reached it)  [truth 114: correct]   compute 51.4
     other answers considered: 128 (0.20, 1 route), 121 (0.06, 2 routes)
```

### Two routes, one answer

```text
Q: What is 575 divided by 25?  (hidden type: div)
  on the table: N1 = 575, N2 = 25
  Step 1: 575 ÷ 25 = 23
      div(N1,N2)   judge 1.00   backed by neural-1 0.99, neural-6 0.99, memory 0.99, neural-7 0.97 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:0, relevance uses:hi
      why: +2.3 by|memory|c9, +1.8 conf:max, +1.4 conf:mean
  Done: the answer is 23
      answer   judge 1.00   backed by memory 0.99, neural-1 0.98, neural-6 0.96, neural-5 0.96 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:hi, relevance open-relevant:0, relevance open-max:lo
      why: +2.3 by|memory|c9, +1.8 conf:max, +1.0 conf:mean
  => 23   probability 1.00 (3 routes reached it)  [truth 23: correct]   compute 71.0
     other answers considered: 48 (0.00, 2 routes), 14375 (0.00, 1 route)
```

### Numbers far bigger than training, exact anyway

```text
Q: Let f(y) = -y^2 - 6*y - 1. What is f(0)?  (hidden type: apply)
  on the table: F1 = f(y) = -y^2 - 6*y - 1, C1 = f(0)
  Step 1: f(0) = -1
      apply(F1,C1)   judge 1.00   backed by apply 0.99, neural-1 0.99, neural-6 0.99, memory 0.99 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:fail:weak, lexicon explains:hi
      why: +2.3 by|memory|c9, +1.8 conf:max, +1.4 conf:mean
  Done: the answer is -1
      answer   judge 1.00   backed by memory 0.99, neural-6 0.96, neural-5 0.96, neural-7 0.94 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:fail:weak, estimator size:loose, lexicon unexplained:0, relevance open-relevant:0, relevance open-max:lo
      why: +2.3 by|memory|c9, +1.8 conf:max, +0.8 conf:mean
  => -1   probability 1.00 (5 routes reached it)  [truth -1: correct]   compute 58.6
     other answers considered: 4 (0.00, 1 route), not enough information (0.00, 11 routes)
```

### A sentence that doesn't matter, left alone

```text
Q: It rained on thirty-one days last month. How much is 75 percent of 600?  (hidden type: percent)
  on the table: N1 = thirty-one, N2 = 75, N3 = 600
  Step 1: 75 × 600 = 45000
      mul(N2,N3)   judge 0.89   backed by mul 0.59, neural-6 0.56, neural-1 0.48, neural-8 0.42 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:lo, relevance uses:hi
      why: −0.7 by|analogy|analogy/sim0, +0.6 by|neural-5|n/c5, −0.6 v|lexicon:explains:lo
      also on the table: none of these 0.11
  Step 2: 45000 ÷ 100 = 450
      div(S1,K100)   judge 0.97   backed by neural-7 0.90, neural-1 0.76, div 0.71, neural-5 0.56 +1 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi
      why: +1.0 v|lexicon:explains:hi, +0.9 conf:max, −0.7 by|analogy|analogy/sim0
      also on the table: answer 0.03 (neural-3+4)
  Done: the answer is 450
      answer   judge 0.99   backed by neural-1 0.98, neural-6 0.96, neural-7 0.94, neural-2 0.90 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:far, lexicon unexplained:hi, relevance open-relevant:1, relevance open-max:mid
      why: +1.6 conf:max, −1.2 v|estimator:size:far, −0.7 by|analogy|analogy/sim0
  => 450   probability 0.85 (1 route reached it)  [truth 450: correct]   compute 54.6
     other answers considered: 45000 (0.02, 1 route), not enough information (0.00, 7 routes)
```

### Not enough information, worked out

```text
Q: The street has 13 houses. What is the average speed of a cyclist who rides 420 km in a few hours?  (hidden type: speed)
  on the table: N1 = 13, N2 = 420, N3 = a few
  Step 1: 420 × [a few] = unknown
      mul(N2,N3)   judge 0.84   backed by neural-8 0.80, neural-2 0.50, neural-5 0.44, mul 0.01
      reviews: lexicon explains:lo, relevance uses:hi
      why: +0.6 conf:max, −0.6 v|lexicon:explains:lo, +0.5 by|neural-8|n/c5
      also on the table: div(N1,N3) 0.05 (div+3), add(N1,N2) 0.03 (neural-6+1), none of these 0.07
  Step 2: 13 + ? = unknown
      add(N1,S1)   judge 0.55   backed by neural-6 0.99, add 0.01
      reviews: lexicon explains:lo, relevance uses:hi
      why: +1.8 conf:max, +0.6 uses-last|1, −0.6 v|lexicon:explains:lo
      also on the table: div(S1,K2) 0.28 (div+3), answer 0.10 (neural-2+4), none of these 0.08
  Done: the answer depends on a quantity the question doesn't give: not enough information
      answer   judge 1.00   backed by goal 0.99, neural-1 0.98, neural-6 0.96, neural-5 0.96 +5 more
      reviews: lexicon unexplained:hi, relevance open-relevant:0, relevance open-max:lo
      why: +1.8 conf:max, +1.2 by|goal|done/c5, +1.0 conf:mean
  => not enough information   probability 0.85 (18 routes reached it)  [truth not enough information: correct]   compute 67.4
     other answers considered: 433 (0.00, 1 route)
```

### Not sure enough, so it abstains

```text
Q: Continue the sequence: 1, -2, 4, -8, 16, -32.  (hidden type: next)
  on the table: L1 = 1, -2, 4, -8, 16, -32
  Step 1: next term of 1, -2, 4, -8, 16, -32 = 64
      next(L1)   judge 0.21   backed by next 0.21
      reviews: checker whole-number:pass:weak, checker not-negative:pass:weak, lexicon explains:0
      why: +0.6 fresh|1/1, −0.5 conf:max, +0.5 by|next
      also on the table: sum(L1) 0.09 (sum+3), mean(L1) 0.06 (mean+5), none of these 0.56
  Done: the answer is 64
      answer   judge 1.00   backed by goal 0.99, neural-1 0.98, neural-6 0.96, neural-5 0.96 +5 more
      reviews: checker whole-number:pass:weak, checker yes-or-no:fail:weak, checker not-negative:pass:weak, estimator size:loose, lexicon unexplained:0, relevance open-relevant:0, relevance open-max:lo
      why: +1.8 conf:max, +1.2 by|goal|done/c5, +1.0 conf:mean
  => abstains: best answer 64 only reached 0.21 (needs 0.50)  [truth 64]
     other answers considered: -21 (0.09, 1 route), -3.5 (0.06, 1 route)
```

### A confident mistake

```text
Q: How many kilometers are there in 12000 meters?  (hidden type: unit_down)
  on the table: N1 = 12000
  Step 1: 12000 ÷ 100 = 120
      div(N1,K100)   judge 1.00   backed by memory 0.99, neural-4 0.45, neural-2 0.33, neural-5 0.32 +4 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:0, relevance uses:hi
      why: +2.3 by|memory|c9, +1.7 conf:max, +0.8 by|div|c0
  Done: the answer is 120
      answer   judge 0.76   backed by goal 0.99, neural-1 0.98, neural-6 0.96, neural-5 0.96 +5 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:hi, relevance open-relevant:0, relevance open-max:lo
      why: +1.8 conf:max, +1.2 by|goal|done/c5, +0.9 conf:mean
      also on the table: div(S1,K10) 0.24 (memory)
  => 120   probability 0.76 (2 routes reached it)  [truth 12: WRONG]   compute 62.6
     other answers considered: 12 (0.24, 1 route), 12000000 (0.00, 1 route)
```

