# The room: a large council that solves maths step by step

42 experts in the room. The curriculum has 75 kinds of question needing one to four steps. 8000 practice questions, half with the answer revealed afterwards and never the method; then six test sets with no answers at all. The room is frozen for testing.

Averaged over 4 seeds (range across seeds in brackets).

## Right answers on each test set (wrong in brackets; the rest are abstentions)

| strategy | seen | paraphrase | big | story | compose | longer |
|---|---|---|---|---|---|---|
| room | 98% (2%) | 75% (13%) | 97% (2%) | 57% (12%) | 39% (27%) | 14% (22%) |
| room, cross-fitted (two sparring benches) | 92% (3%) | 55% (10%) | 96% (1%) | 15% (8%) | 23% (12%) | 0% (8%) |
| room, one neural expert | 98% (1%) | 77% (9%) | 98% (2%) | 44% (8%) | 52% (19%) | 0% (19%) |
| room, operators only | 89% (3%) | 71% (8%) | 92% (2%) | 38% (1%) | 53% (13%) | 1% (10%) |
| council v2 (question -> answer) | 87% (2%) | 54% (9%) | 97% (0%) | 64% (30%) | 8% (43%) | 0% (42%) |

- **seen**: familiar wording, new numbers
- **paraphrase**: wording never seen in training
- **big**: numbers ~100x bigger than training
- **story**: word problems (1-3 steps): new names, objects and phrasings
- **compose**: combinations of familiar steps never seen together (2-3 steps)
- **longer**: four-step problems, longer than anything in training

Spread across seeds for the room (lowest-highest accuracy):

| | seen | paraphrase | big | story | compose | longer |
|---|---|---|---|---|---|---|
| room | 96%-100% | 72%-80% | 96%-98% | 36%-73% | 34%-46% | 0%-50% |

## Right for the right reason

Of the right answers, how many used the same method as the hidden reference program (commutative arguments aside)? A different valid method also counts as right above.

| strategy | seen | paraphrase | big | story | compose | longer |
|---|---|---|---|---|---|---|
| room | 89% | 92% | 93% | 95% | 91% | 25% |
| room, cross-fitted (two sparring benches) | 95% | 97% | 96% | 75% | 96% | 0% |
| room, one neural expert | 93% | 96% | 94% | 100% | 99% | 0% |
| room, operators only | 96% | 98% | 98% | 100% | 94% | 0% |

## Division of labour (seed 0)

Share of the steps in right test solutions that each kind of expert backed (a step can have several backers).

| test set | operator | neural | memory | analogy | goal |
|---|---|---|---|---|---|
| seen | 57% | 99% | 99% | 1% | 42% |
| paraphrase | 53% | 99% | 0% | 93% | 47% |
| big | 50% | 99% | 100% | 0% | 49% |
| story | 52% | 100% | 0% | 100% | 48% |
| compose | 69% | 100% | 0% | 39% | 31% |
| longer | 80% | 100% | 0% | 0% | 20% |

The neural pool is trained as a mixture of experts: each worked step is shared out in proportion to how well each network already predicts it. Where each network's correct backing concentrates (seed 0):

| expert | most backed kind of question | share | entropy (bits) |
|---|---|---|---|
| neural-1 | solve_sq_add | 4% | 5.90 |
| neural-2 | apply_mul | 3% | 5.89 |
| neural-3 | story_three | 3% | 5.87 |
| neural-4 | story_three | 4% | 5.91 |
| neural-5 | solve_sq_add | 4% | 5.90 |
| neural-6 | story_three | 4% | 5.87 |
| neural-7 | story_three | 4% | 5.85 |
| neural-8 | apply_mul | 3% | 5.89 |

## The 40-question exam

The hand-written exam from `maths/exam.py` (new numbers, 18 new wordings), now answered step by step.

| | right | wrong | abstained |
|---|---|---|---|
| room | 34 | 2 | 4 |
| council v2 (question -> answer) | 31 | 5 | 4 |

Training accuracy per 1000 questions (room, seed 0): 69%, 93%, 94%, 97%, 98%, 99%, 99%, 99%

Seed 0: {'searched': 213, 'found': 207, 'own_solution': 3823, 'certified': 3571}

## Sample deliberations (seed 0, auto-picked)

### A three-step word problem, every expert in its lane

```text
Q: Rosa collected 37 buttons, was given 23 more, then gave 4 away. How many buttons does Rosa have left?  (hidden type: story_gain_lose)
  on the table: N1 = 37, N2 = 23, N3 = 4
  Step 1: 37 + 23 = 60
      add(N1,N2)   judge 0.50   backed by neural-7 0.49, neural-8 0.41, neural-2 0.36, analogy 0.29 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi
      why: +1.1 v|lexicon:explains:hi, −0.7 uses-last|none, +0.6 fresh|2/2
      also on the table: sub(N2,N3) 0.01 (sub), none of these 0.47
  Step 2: 60 − 4 = 56
      sub(S1,N3)   judge 1.00   backed by neural-7 0.98, neural-2 0.95, neural-6 0.92, neural-5 0.84 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi
      why: +1.6 conf:max, +1.1 v|lexicon:explains:hi, +1.1 uses-last|1
  Done: the answer is 56
      answer   judge 1.00   backed by goal 0.99, neural-6 0.96, neural-7 0.96, neural-5 0.96 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:0
      why: +1.9 conf:max, +1.1 conf:mean, +0.7 stop|open:0
  => 56   probability 0.50 (2 routes reached it)  [truth 56: correct]   compute 76.9
     other answers considered: 847 (0.00, 1 route), 19 (0.00, 1 route)
```

### A combination never seen in training

```text
Q: Let p(x) = 4*x - 6. What is p(1) plus 2?  (hidden type: apply_add)
  on the table: N1 = 2, F1 = p(x) = 4*x - 6, C1 = p(1)
  Step 1: p(1) = -2
      apply(F1,C1)   judge 1.00   backed by apply 0.99, analogy 0.99, neural-5 0.99, neural-7 0.98 +5 more
      reviews: checker whole-number:pass:trusted, checker not-negative:fail:weak, lexicon explains:hi
      why: +1.9 conf:max, +1.5 conf:mean, +1.1 v|lexicon:explains:hi
  Step 2: 2 + -2 = 0
      add(N1,S1)   judge 0.52   backed by add 0.99, neural-3 0.80, neural-4 0.67, neural-8 0.38 +1 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:weak, lexicon explains:mid
      why: +1.9 conf:max, +1.1 uses-last|1, +0.6 fresh|2/2
      also on the table: mul(N1,S1) 0.47 (mul+4)
  Done: the answer is 0
      answer   judge 1.00   backed by goal 0.99, neural-6 0.96, neural-7 0.96, neural-5 0.96 +5 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:pass:weak, checker not-negative:pass:weak, estimator size:close, lexicon unexplained:0
      why: +1.9 conf:max, +1.2 conf:mean, +0.7 stop|open:0
  => 0   probability 0.52 (3 routes reached it)  [truth 0: correct]   compute 80.7
     other answers considered: -4 (0.47, 2 routes), -2 (0.00, 2 routes)
```

### Four steps, longer than anything in training

```text
Q: Priya has 52 beads. Priya buys 4 bags with 10 beads in each bag, then gives away 7. Priya shares the rest equally among 5 friends. How many beads does each friend get?  (hidden type: story_four)
  on the table: N1 = 52, N2 = 4, N3 = 10, N4 = 7, N5 = 5
  Step 1: 4 × 10 = 40
      mul(N2,N3)   judge 0.88   backed by neural-7 0.98, neural-6 0.92, neural-5 0.84, neural-1 0.82 +5 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:weak, lexicon explains:hi
      why: +1.6 conf:max, +1.1 v|lexicon:explains:hi, −0.7 uses-last|none
      also on the table: none of these 0.10
  Step 2: 52 + 40 = 92
      add(N1,S1)   judge 1.00   backed by add 0.99, neural-5 0.99, neural-7 0.98, neural-6 0.98 +4 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:weak, lexicon explains:mid
      why: +1.9 conf:max, +1.5 conf:mean, +1.1 uses-last|1
  Step 3: 92 − 7 = 85
      sub(S2,N4)   judge 0.94   backed by neural-6 0.61, neural-4 0.47, sub 0.18
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:weak, lexicon explains:hi
      why: +1.1 v|lexicon:explains:hi, +1.1 uses-last|1, +0.6 fresh|2/2
      also on the table: answer 0.01 (neural-1+6), none of these 0.04
  Step 4: 85 ÷ 5 = 17
      div(S3,N5)   judge 0.67   backed by neural-3 0.32, div 0.00
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:weak, lexicon explains:hi
      why: +1.1 v|lexicon:explains:hi, +1.1 uses-last|1, −1.1 conf:mean
      also on the table: answer 0.26 (neural-1+6), none of these 0.05
  Done: the answer is 17
      answer   judge 1.00   backed by goal 0.99, neural-6 0.96, neural-7 0.96, neural-5 0.96 +5 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:weak, estimator size:close, lexicon unexplained:0
      why: +1.9 conf:max, +1.1 conf:mean, +0.7 stop|open:0
  => 17   probability 0.56 (1 route reached it)  [truth 17: correct]   compute 76.9
     other answers considered: 85 (0.21, 1 route), 92 (0.01, 1 route)
```

### Two routes, one answer

```text
Q: Is 83 bigger than -19?  (hidden type: gt)
  on the table: N1 = 83, N2 = -19
  Step 1: is 83 > -19? yes (1)
      gt(N1,N2)   judge 1.00   backed by gt 0.99, memory 0.99, neural-5 0.99, neural-7 0.98 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi
      why: +1.9 conf:max, +1.5 by|memory|c9, +1.4 conf:mean
  Done: the answer is 1
      answer   judge 1.00   backed by memory 0.99, goal 0.99, neural-6 0.96, neural-7 0.96 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:pass:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:hi
      why: +1.9 conf:max, +1.5 by|memory|c9, +1.3 conf:mean
  => 1   probability 1.00 (10 routes reached it)  [truth 1: correct]   compute 76.4
     other answers considered: 102 (0.00, 1 route), 1577 (0.00, 1 route)
```

### Numbers far bigger than training, exact anyway

```text
Q: Is 2600 greater than -4700?  (hidden type: gt)
  on the table: N1 = 2600, N2 = -4700
  Step 1: is 2600 > -4700? yes (1)
      gt(N1,N2)   judge 1.00   backed by gt 0.99, memory 0.99, neural-7 0.98, neural-6 0.98 +6 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi
      why: +1.9 conf:max, +1.5 by|memory|c9, +1.1 conf:mean
  Done: the answer is 1
      answer   judge 1.00   backed by memory 0.99, goal 0.99, neural-6 0.96, neural-7 0.96 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:pass:weak, checker not-negative:pass:trusted, estimator size:loose, lexicon unexplained:hi
      why: +1.9 conf:max, +1.5 by|memory|c9, +1.3 conf:mean
  => 1   probability 1.00 (11 routes reached it)  [truth 1: correct]   compute 76.4
     other answers considered: 2599 (0.00, 1 route), 122200 (0.00, 1 route)
```

### Not sure enough, so it abstains

```text
Q: How many days are in 17 weeks?  (hidden type: unit_up)
  on the table: N1 = 17
  Step 1: 17 × 7 = 119
      mul(N1,K7)   judge 0.30   backed by analogy 0.92, neural-7 0.34, neural-5 0.06, neural-6 0.04 +1 more
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi
      why: +1.1 v|lexicon:explains:hi, +1.0 conf:max, −0.7 fresh|1/2
      also on the table: div(N1,K7) 0.01 (div+5), none of these 0.68
  Done: the answer is 119
      answer   judge 0.99   backed by goal 0.99, neural-6 0.96, neural-7 0.96, neural-8 0.95 +6 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:hi
      why: +1.9 conf:max, +1.1 conf:mean, +0.7 stop|open:0
  => abstains: best answer 119 only reached 0.29 (needs 0.50)  [truth 119]
     other answers considered: 2.42857 (0.01, 1 route), 4913 (0.00, 1 route)
```

### A confident mistake

```text
Q: How many grams are in 24 kilograms?  (hidden type: unit_up)
  on the table: N1 = 24
  Step 1: 24 × 10 = 240
      mul(N1,K10)   judge 0.67   backed by analogy 0.92
      reviews: checker whole-number:pass:trusted, checker not-negative:pass:trusted, lexicon explains:hi
      why: +1.1 v|lexicon:explains:hi, +1.0 conf:max, +1.0 conf:mean
      also on the table: div(N1,K12) 0.06 (div+6), none of these 0.27
  Done: the answer is 240
      answer   judge 0.85   backed by neural-6 0.96, neural-8 0.95, goal 0.95, neural-2 0.93 +3 more
      reviews: checker whole-number:pass:trusted, checker yes-or-no:fail:weak, checker not-negative:pass:trusted, estimator size:close, lexicon unexplained:hi
      why: +1.3 conf:max, +0.9 conf:mean, +0.7 stop|open:0
      also on the table: mul(S1,K100) 0.11 (mul+3), div(S1,N1) 0.02 (div), none of these 0.02
  => 240   probability 0.57 (1 route reached it)  [truth 24000: WRONG]   compute 73.5
     other answers considered: 24000 (0.07, 2 routes), 2 (0.05, 1 route)
```

