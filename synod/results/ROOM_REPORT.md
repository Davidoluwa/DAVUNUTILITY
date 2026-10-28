# The room: a large council that solves maths step by step

43 experts in the room at the start (seed 0 ended with 45, after inventing 2 procedures). The curriculum has 75 kinds of question needing one to four steps; a quarter of the word problems carry a sentence that doesn't matter, and some questions leave out a number they need. 8000 practice questions, half with the answer revealed afterwards (never the method); then eight test sets with no answers at all. The room is frozen for testing.

Averaged over 3 seeds (range across seeds below).

## Right answers on each test set (wrong in brackets; the rest are abstentions)

| strategy | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| room | 95% (4%) | 70% (20%) | 98% (2%) | 54% (25%) | 33% (48%) | 1% (62%) | 22% (24%) | 78% (6%) |
| room, without inventing procedures | 95% (3%) | 72% (15%) | 97% (2%) | 53% (18%) | 36% (40%) | 8% (44%) | 19% (21%) | 70% (5%) |
| room, one neural expert | 95% (2%) | 73% (15%) | 98% (2%) | 53% (19%) | 41% (36%) | 10% (59%) | 18% (19%) | 60% (7%) |
| operators alone (no neural, memory or analogy) | 90% (1%) | 63% (10%) | 91% (0%) | 44% (4%) | 44% (12%) | 0% (12%) | 6% (5%) | 43% (0%) |
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
| room | 94%-96% | 66%-74% | 96%-100% | 41%-66% | 28%-42% | 0%-4% | 18%-24% | 68%-86% |
| room, without inventing procedures | 91%-97% | 70%-76% | 96%-98% | 51%-56% | 26%-44% | 0%-22% | 10%-28% | 46%-86% |
| room, one neural expert | 93%-98% | 70%-76% | 97%-99% | 50%-59% | 39%-44% | 0%-31% | 8%-24% | 48%-72% |
| operators alone (no neural, memory or analogy) | 86%-93% | 59%-67% | 89%-93% | 37%-49% | 20%-62% | 0%-0% | 3%-11% | 41%-47% |

## Relevance and missing information

How often each room said "not enough information". On the missing set that's the right answer; anywhere else it's a false alarm (and counted as wrong above).

| strategy | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| room | 0% | 0% | 0% | 0% | 0% | 0% | 2% | 78% |
| room, without inventing procedures | 0% | 0% | 0% | 0% | 0% | 0% | 2% | 70% |
| room, one neural expert | 0% | 0% | 0% | 0% | 0% | 0% | 1% | 60% |
| operators alone (no neural, memory or analogy) | 0% | 0% | 0% | 0% | 0% | 0% | 1% | 43% |

## Inventing procedures

Every 1000 practice questions the room sleeps on 300 of its past worked solutions. If its notebook shows a recurring piece, a copy of the room adopts it as a new operation (with its own expert) and sleeps on the same solutions re-expressed with it. Both then meet the next 500 questions before learning from them. The copy replaces the room only if it was less surprised by the worked solutions (total -log probability, in nats), used the procedure, and lost no more answers than it won.

Seed 0:

| at question | procedure | seen in notebook | surprise: room / copy | answers won-lost | copy used it | kept |
|---|---|---|---|---|---|---|
| 1500 | `(a × b) − c` | 35x in 9 wordings | 153.7 / 154.3 | 1-0 | 13 | dropped |
| 3000 | `a + ((b × c) − d)` | 35x in 31 wordings | 46.7 / 44.0 | 0-0 | 3 | **kept** |
| 4500 | `(a + b) ÷ c` | 79x in 41 wordings | 126.6 / 131.9 | 0-0 | 6 | dropped |
| 6000 | `a − (b × c)` | 98x in 80 wordings | 56.0 / 44.5 | 0-0 | 7 | **kept** |
| 7500 | `(a + b) − c` | 105x in 88 wordings | 49.0 / 49.5 | 0-0 | 11 | dropped |

Seed 1:

| at question | procedure | seen in notebook | surprise: room / copy | answers won-lost | copy used it | kept |
|---|---|---|---|---|---|---|
| 1500 | `(a × b) − c` | 29x in 15 wordings | 100.4 / 100.9 | 0-1 | 12 | dropped |
| 3000 | `a + ((b × c) − d)` | 26x in 23 wordings | 97.8 / 125.9 | 0-3 | 3 | dropped |
| 4500 | `(a + b) ÷ c` | 75x in 31 wordings | 48.7 / 53.9 | 0-0 | 14 | dropped |
| 6000 | `a − (b × c)` | 97x in 73 wordings | 16.0 / 13.8 | 0-0 | 4 | **kept** |
| 7500 | `(a + b) − c` | 100x in 87 wordings | 22.6 / 45.1 | 0-0 | 8 | dropped |

Seed 2:

| at question | procedure | seen in notebook | surprise: room / copy | answers won-lost | copy used it | kept |
|---|---|---|---|---|---|---|
| 1500 | `(a + b) ÷ c` | 37x in 19 wordings | 180.8 / 153.0 | 0-0 | 8 | **kept** |
| 3000 | `(a + b) − c` | 74x in 70 wordings | 152.7 / 217.3 | 0-0 | 5 | dropped |
| 4500 | `a + (b × c)` | 78x in 70 wordings | 35.5 / 88.2 | 0-0 | 8 | dropped |
| 6000 | `(a + (b × c)) − d` | 52x in 46 wordings | 85.8 / 122.4 | 0-0 | 4 | dropped |
| 7500 | `a − (b × c)` | 108x in 92 wordings | 64.7 / 61.4 | 0-0 | 2 | dropped |

Share of right test answers that used an invented procedure (mean over seeds):

| | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| room | 2% | 0% | 0% | 7% | 3% | 0% | 10% | 5% |

Useful invention: the room minus the same room that never invents (right answers, same beam):

| | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| difference | +0 | -3 | +0 | +1 | -3 | -6 | +2 | +8 |

## Right for the right reason

Of the right answers, how many used the same method as the hidden reference program (commutative arguments aside; invented procedures written out)? On the distract set that means it left the sentences that don't matter alone.

| strategy | seen | paraphrase | big | story | compose | longer | distract | missing |
|---|---|---|---|---|---|---|---|---|
| room | 95% | 98% | 92% | 100% | 96% | 0% | 92% | 100% |
| room, without inventing procedures | 95% | 96% | 93% | 97% | 99% | 0% | 85% | 100% |
| room, one neural expert | 92% | 93% | 93% | 95% | 100% | 0% | 98% | 100% |
| operators alone (no neural, memory or analogy) | 95% | 97% | 95% | 100% | 93% | 0% | 92% | 100% |

## Division of labour (seed 0)

Share of the steps in right test solutions that each kind of expert backed (a step can have several backers).

| test set | operator | neural | memory | analogy | goal |
|---|---|---|---|---|---|
| seen | 59% | 100% | 98% | 2% | 41% |
| paraphrase | 51% | 94% | 0% | 94% | 49% |
| big | 51% | 100% | 100% | 0% | 49% |
| story | 54% | 100% | 0% | 91% | 46% |
| compose | 67% | 100% | 0% | 33% | 33% |
| longer | 0% | 0% | 0% | 0% | 0% |
| distract | 56% | 96% | 0% | 45% | 43% |
| missing | 54% | 100% | 0% | 22% | 46% |

The neural pool is trained as a mixture of experts: each worked step is shared out in proportion to how well each network already predicts it. Where each network's correct backing concentrates (seed 0):

| expert | most backed kind of question | share | entropy (bits) |
|---|---|---|---|
| neural-1 | story_gain_lose | 5% | 5.71 |
| neural-2 | story_change | 4% | 5.75 |
| neural-3 | apply_mul | 4% | 5.78 |
| neural-4 | story_sub | 4% | 5.81 |
| neural-5 | story_gain_lose | 5% | 5.70 |
| neural-6 | story_gain_lose | 5% | 5.76 |
| neural-7 | story_gain_lose | 4% | 5.72 |
| neural-8 | story_div | 4% | 5.77 |

## The 40-question exam

The hand-written exam from `maths/exam.py` (new numbers, 18 new wordings), now answered step by step.

| | right | wrong | abstained |
|---|---|---|---|
| room | 32 | 7 | 1 |
| council v2 (question -> answer) | 27 | 0 | 13 |

Training accuracy per 1000 questions (room, seed 0): 51%, 86%, 91%, 94%, 94%, 96%, 96%, 96%

Seed 0: {'searched': 390, 'found': 357, 'own_solution': 3600, 'certified': 3244, 'told_insufficient': 3}

Wall-clock per run (practice + all test sets, one core each, four at a time): room 365s, room, without inventing procedures 249s, room, one neural expert 262s, operators alone (no neural, memory or analogy) 187s, search alone, no learning 102s, council v2 (question -> answer) 236s

## Sample deliberations (seed 0, auto-picked)

### A three-step word problem, every expert in its lane

```text
Q: Kofi collected 12 stamps, was given 16 more, then gave 11 away. How many stamps does Kofi have left?  (hidden type: story_gain_lose)
  on the table: N1 = 12, N2 = 16, N3 = 11
  Step 1: 12 + 16 = 28
      add(N1,N2)   judge 0.51   backed by neural-2 0.48, neural-6 0.44, analogy 0.29, neural-5 0.28 +3 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi, relevance uses:hi
      why: +1.2 v|lexicon:explains:hi, −0.6 by|analogy|analogy/sim0, −0.4 fam:0
      also on the table: sub(N2,N3) 0.25 (sub+3), none of these 0.23
  Step 2: 28 − 11 = 17
      sub(S1,N3)   judge 0.98   backed by sub 0.85, neural-6 0.67, neural-7 0.47, neural-5 0.39 +2 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi, relevance uses:hi
      why: +1.2 v|lexicon:explains:hi, −0.6 by|analogy|analogy/sim0, +0.6 conf:max
      also on the table: answer 0.01 (neural-2+4)
  Done: the answer is 17
      answer   judge 1.00   backed by goal 0.99, neural-1 0.94, neural-5 0.93, neural-7 0.91 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:mid, relevance open-relevant:0, relevance open-max:lo
      why: +1.6 conf:max, −1.2 v|checker:yes-or-no:fail:weak, +0.9 conf:mean
  => 17   probability 0.50 (2 routes reached it)  [truth 17: correct]   compute 54.2
     other answers considered: 5 (0.24, 1 route), -116 (0.01, 1 route)
```

### A combination never seen in training

```text
Q: What is the mean of 27, 15, 14, 37, 5, 34, multiplied by 12?  (hidden type: mean_mul)
  on the table: N1 = 12, L1 = 27, 15, 14, 37, 5, 34
  Step 1: mean of 27, 15, 14, 37, 5, 34 = 22
      mean(L1)   judge 1.00   backed by neural-2 0.96, neural-8 0.95, neural-6 0.95, neural-3 0.90 +3 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi
      why: +1.2 v|lexicon:explains:hi, +1.1 conf:max, +0.7 by|neural-3|n/c5
  Step 2: 12 × 22 = 264
      mul(N1,S1)   judge 0.89   backed by mul 0.99, neural-7 0.93, neural-1 0.52
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:0, relevance uses:hi
      why: +1.4 conf:max, +1.1 conf:mean, +0.6 by|neural-7|c9
      also on the table: add(N1,S1) 0.10 (add+5)
  Done: the answer is 264
      answer   judge 1.00   backed by goal 0.99, neural-1 0.94, neural-5 0.93, neural-7 0.91 +5 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:far, lexicon unexplained:hi, relevance open-relevant:0, relevance open-max:lo
      why: −1.8 v|estimator:size:far, +1.6 conf:max, −1.2 v|checker:yes-or-no:fail:weak
  => 264   probability 0.89 (1 route reached it)  [truth 264: correct]   compute 48.8
     other answers considered: 34 (0.10, 1 route), 22 (0.00, 3 routes)
```

### Two routes, one answer

```text
Q: What is 575 divided by 25?  (hidden type: div)
  on the table: N1 = 575, N2 = 25
  Step 1: 575 ÷ 25 = 23
      div(N1,N2)   judge 1.00   backed by div 0.99, memory 0.99, neural-2 0.96, neural-8 0.95 +5 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:0, relevance uses:hi
      why: +1.6 conf:max, +1.4 conf:mean, +1.2 by|memory|c9
  Done: the answer is 23
      answer   judge 1.00   backed by memory 0.99, neural-1 0.94, neural-5 0.93, neural-7 0.91 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:hi, relevance open-relevant:0, relevance open-max:lo
      why: +1.6 conf:max, +1.2 by|memory|c9, −1.2 v|checker:yes-or-no:fail:weak
  => 23   probability 1.00 (4 routes reached it)  [truth 23: correct]   compute 50.5
     other answers considered: 0 (0.00, 1 route), 14375 (0.00, 1 route)
```

### Numbers far bigger than training, exact anyway

```text
Q: Let f(y) = -y^2 - 6*y - 1. What is f(0)?  (hidden type: apply)
  on the table: F1 = f(y) = -y^2 - 6*y - 1, C1 = f(0)
  Step 1: f(0) = -1
      apply(F1,C1)   judge 1.00   backed by apply 0.99, memory 0.99, neural-2 0.96, neural-8 0.95 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:fail:weak, lexicon explains:hi
      why: +1.6 conf:max, +1.4 conf:mean, +1.2 by|memory|c9
  Done: the answer is -1
      answer   judge 1.00   backed by memory 0.99, neural-1 0.94, neural-5 0.93, neural-7 0.91 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:fail:weak, estimator size:loose, lexicon unexplained:0, relevance open-relevant:0, relevance open-max:lo
      why: +1.6 conf:max, +1.2 by|memory|c9, −1.2 v|checker:yes-or-no:fail:weak
  => -1   probability 1.00 (1 route reached it)  [truth -1: correct]   compute 50.0
     other answers considered: 1 (0.00, 1 route), -4 (0.00, 1 route)
```

### A sentence that doesn't matter, left alone

```text
Q: It rained on thirty-one days last month. How much is 75 percent of 600?  (hidden type: percent)
  on the table: N1 = thirty-one, N2 = 75, N3 = 600
  Step 1: 75 × 600 = 45000
      mul(N2,N3)   judge 1.00   backed by neural-2 0.67, neural-3 0.60, neural-6 0.59, neural-8 0.56 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:0, relevance uses:hi
      why: +0.7 by|neural-3|n/c5, +0.6 by|neural-6|n/c5, −0.6 by|analogy|analogy/sim0
  Step 2: 45000 ÷ 100 = 450
      div(S1,K100)   judge 0.93   backed by neural-8 0.56, neural-1 0.52, neural-5 0.48, div 0.40 +2 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi
      why: +1.2 v|lexicon:explains:hi, −0.6 by|analogy|analogy/sim0, +0.5 by|div|f0
      also on the table: answer 0.06 (neural-2+4), none of these 0.01
  Done: the answer is 450
      answer   judge 0.96   backed by neural-1 0.94, neural-5 0.93, neural-7 0.91, neural-6 0.89 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:far, lexicon unexplained:hi, relevance open-relevant:1, relevance open-max:mid
      why: −1.8 v|estimator:size:far, −1.2 v|checker:yes-or-no:fail:weak, +0.9 conf:max
      also on the table: none of these 0.03
  => 450   probability 0.89 (1 route reached it)  [truth 450: correct]   compute 44.6
     other answers considered: 45000 (0.06, 1 route), 13950 (0.00, 1 route)
```

### Not enough information, worked out

```text
Q: What do you get if you increase 400 by a few percent?  (hidden type: pct_up)
  on the table: N1 = 400, N2 = a few
  Step 1: 400 × [a few] = unknown
      mul(N1,N2)   judge 0.96   backed by neural-8 0.95, neural-6 0.95, neural-1 0.94, neural-5 0.93 +4 more
      reviews: lexicon explains:0, relevance uses:hi
      why: +1.0 conf:max, +0.9 conf:mean, +0.6 by|neural-6|n/c5
      also on the table: div(N1,K100) 0.02 (div+1), none of these 0.01
  Step 2: ? ÷ 100 = unknown
      div(S1,K100)   judge 0.81   backed by neural-5 0.93, div 0.68, neural-1 0.52, analogy 0.48
      reviews: lexicon explains:hi
      why: +1.2 v|lexicon:explains:hi, +0.9 conf:max, +0.5 by|div|f0
      also on the table: answer 0.18 (neural-2+6)
  Done: the answer depends on a quantity the question doesn't give: not enough information
      answer   judge 1.00   backed by goal 0.99, neural-1 0.94, neural-5 0.93, neural-7 0.91 +4 more
      reviews: lexicon unexplained:hi, relevance open-relevant:0, relevance open-max:lo
      why: +1.6 conf:max, +0.8 conf:mean, +0.7 by|goal|done/c5
  => not enough information   probability 0.96 (13 routes reached it)  [truth not enough information: correct]   compute 50.0
     other answers considered: 404 (0.01, 1 route), 4.04 (0.00, 1 route)
```

### An invented procedure at work

```text
Q: Jamal has 15 cookies. Jamal buys 3 bags with 7 cookies in each bag, then gives away 22. How many cookies does Jamal have now?  (hidden type: story_three)
  on the table: N1 = 15, N2 = 3, N3 = 7, N4 = 22
  Step 1: proc_8e94a(15, 3, 7, 22) = 14  (invented: a + ((b × c) − d))
      proc_8e94a(N1,N2,N3,N4)   judge 1.00   backed by proc_8e94a 0.99, neural-8 0.95, neural-1 0.94, neural-5 0.93 +2 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:weak, lexicon explains:hi, relevance uses:hi
      why: +1.6 conf:max, +1.3 conf:mean, +1.2 v|lexicon:explains:hi
  Done: the answer is 14
      answer   judge 1.00   backed by goal 0.99, neural-1 0.94, neural-5 0.93, analogy 0.92 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:hi, relevance open-relevant:0, relevance open-max:lo
      why: +1.6 conf:max, −1.2 v|checker:yes-or-no:fail:weak, +1.1 conf:mean
  => 14   probability 1.00 (11 routes reached it)  [truth 14: correct]   compute 48.3
     other answers considered: -1 (0.00, 1 route), 36 (0.00, 1 route)
```

### Not sure enough, so it abstains

```text
Q: A triangle has a base of 29 cm and a height of 8 cm. What is its area?  (hidden type: tri_area)
  on the table: N1 = 29, N2 = 8
  Step 1: lcm(29, 8) = 232
      lcm(N1,N2)   judge 0.89   backed by memory 0.93, neural-7 0.93, lcm 0.73
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi, relevance uses:hi
      why: +1.2 by|memory|c9, +1.2 v|lexicon:explains:hi, +0.9 conf:mean
      also on the table: add(N1,N2) 0.10 (add+3), mul(N1,N2) 0.01 (mul+3)
  Step 2: 232 ÷ 2 = 116
      div(S1,K2)   judge 0.50   backed by memory 0.93, neural-5 0.93, div 0.41
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:0
      why: +1.2 by|memory|c9, +0.9 conf:max, +0.7 conf:mean
      also on the table: answer 0.50 (neural-1+7)
  Done: the answer is 116
      answer   judge 1.00   backed by memory 0.99, goal 0.95, neural-1 0.94, neural-5 0.93 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:hi, relevance open-relevant:0, relevance open-max:lo
      why: +1.6 conf:max, +1.2 by|memory|c9, −1.2 v|checker:yes-or-no:fail:weak
  => abstains: best answer 116 only reached 0.46 (needs 0.50)  [truth 116]
     other answers considered: 232 (0.44, 2 routes), 37 (0.07, 1 route)
```

### A confident mistake

```text
Q: How many kilometers are there in 12000 meters?  (hidden type: unit_down)
  on the table: N1 = 12000
  Step 1: 12000 × 1000 = 12000000
      mul(N1,K1000)   judge 0.99   backed by mul 0.87, neural-8 0.73, neural-3 0.72, neural-2 0.70 +2 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi, relevance uses:hi
      why: +1.2 v|lexicon:explains:hi, +0.7 by|neural-3|n/c5, +0.7 by|memory|exact/seen1
  Done: the answer is 12000000
      answer   judge 1.00   backed by memory 0.98, neural-7 0.91, neural-6 0.89, neural-2 0.87 +3 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:far, lexicon unexplained:mid, relevance open-relevant:0, relevance open-max:lo
      why: −1.8 v|estimator:size:far, +1.4 conf:max, +1.2 by|memory|c9
  => 12000000   probability 0.99 (1 route reached it)  [truth 12: WRONG]   compute 52.1
     other answers considered: 144000000 (0.01, 1 route), 120 (0.00, 4 routes)
```

