# Synod does maths - run report

Nobody tells the system what any wording means. It gets 4000 practice questions (half with the answer revealed afterwards), then five test sets with **no answers at all**. The teacher variant may ask for the answer to questions it couldn't settle, after answering them, up to a small budget.

Averaged over 3 seeds.

## Accuracy on each test set (wrong answers in brackets; the rest are abstentions)

| strategy | seen | paraphrase | big | story | compose |
|---|---|---|---|---|---|
| synod | 100% (0%) | 75% (7%) | 99% (0%) | 63% (7%) | 10% (39%) |
| parser alone (symbolic) | 100% (0%) | 69% (4%) | 99% (0%) | 73% (0%) | 51% (0%) |
| reader alone (neural) | 97% (0%) | 82% (10%) | 97% (0%) | 58% (12%) | 1% (83%) |
| hand-written gate | 99% (0%) | 66% (10%) | 99% (0%) | 52% (4%) | 1% (91%) |
| synod + teacher (asks ≤40) | 100% (0%) | 81% (6%) | 100% (0%) | 96% (0%) | 87% (11%) |

- **seen**: familiar wording, new numbers
- **paraphrase**: wording never seen in training
- **big**: numbers ~100x bigger than training
- **story**: word problems: new names, objects, phrasing
- **compose**: two-step combinations never seen

The teacher variant asked 36 questions on average (out of 1250 test questions).

Training accuracy per 500 questions (synod): 66%, 94%, 97%, 99%, 99%, 99%, 99%, 100%

## Inside one run (seed 0, with teacher)

- Wordings the parser knows: 344; programs the reader can produce: 106.
- Questions it asked the teacher about, by hidden type: unit_down 5, unit_up 5, mod 3, comp_lcm_sub 3, comp_solve_mul 3, sub 2, lmin 2, story_mul 2, comp_solve_prime 2, comp_apply_add 2, lcm 1, story_sub 1, square 1, median 1, next 1, add 1, lmax 1, mean 1, smaller 1, slope 1, story_div 1.
- The parser adopted 31 new wordings from peers' answers after checking them itself, and turned down 2 it couldn't corroborate.
- The reader refused to teach itself from its own answers on new ground 21 times.

Who answered each test set:

| test set | answered by |
|---|---|
| seen | parser 99%, reader 1%, abstain 0% |
| paraphrase | parser 66%, abstain 23%, reader 11% |
| big | parser 100% |
| story | parser 86%, abstain 10%, reader 3% |
| compose | parser 92%, reader 6%, abstain 2% |

What the parser thinks words mean (learned, strongest cues per operation):

- `solve`: suppose, at, derivative
- `add`: more, box, added
- `mul`: times, multiplied, multiply
- `div`: equally, friends, friend
- `sub`: away, gives, left
- `apply`: let, times
- `mod`: remainder, modulo, when
- `gcd`: greatest, divisor, factor
- `lcm`: multiple, least, smallest
- `next`: next, comes, sequence
- `lmin`: lowest, smallest, value
- `at`: evaluate, value, at
- `slope`: derivative, differentiate, respect
- `min`: smaller, less, or
- `sqrt`: root, square
- `pow`: power, raised, to
- `median`: median
- `square`: squared, square
- `calc`: evaluate
- `lmax`: largest, biggest, value
- `sum`: total
- `mean`: mean, average
- `max`: bigger, greater, or
- `is_prime`: prime, a, number

## Sample deliberations (seed 0, auto-picked)

### Exact on numbers far bigger than anything in training

```text
Q #4501: What is z in 5*z + 500 = 4000?  (hidden type: solve)
  parser    bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  reader    bids p=0.99 (calibrated 0.94), needs 0.0 more compute
  -> parser leads: 700  conf 0.99  because solve(equation)  [wording seen before (15 confirmations)]
     parser skips review (not worth the compute at this confidence)
  => answers 700 from parser (belief 0.99)  [truth 700: correct]  compute 0.7
     (unlabeled task: answer certified as teaching signal for the others)
```

### A word problem with a new name, object and phrasing

```text
Q #4750: Kofi had 29 cards and used 8. How many cards remain?  (hidden type: story_sub)
  parser    bids p=0.64 (calibrated 0.72), needs 0.0 more compute
  reader    bids p=0.92 (calibrated 0.87), needs 0.0 more compute
  -> parser leads: 21  conf 0.72  because (n1 - n2)  [like 'grace had # pencils grace lost # of them how many pencils does grace have left' (0.11); cues: 'had'->sub]
     parser asks checker for review -> endorses: passes whole-number   (belief 0.77 -> 0.83)
     parser asks estimator for review -> abstains: never seen questions like this; no feel for the size   (belief 0.83 -> 0.83)
  => answers 21 from parser (belief 0.83)  [truth 21: correct]  compute 4.5
     (unlabeled task: answer certified as teaching signal for the others)
```

### A paraphrase, handled by analogy with a known wording

```text
Q #4251: Find the value of k + 3 when k = -3.  (hidden type: at)
  parser    bids p=1.00 (calibrated 0.98), needs 0.0 more compute
  reader    bids p=0.96 (calibrated 0.96), needs 0.0 more compute
  -> parser leads: 0  conf 0.98  because expr(solve(equation))  [like 'what is the value of <poly> when <eq>' (0.70); cues: 'when'->solve, 'value'->at]
     parser asks checker for review -> endorses: passes whole-number   (belief 0.99 -> 0.99)
  => answers 0 from parser (belief 0.99)  [truth 0: correct]  compute 4.2
     (unlabeled task: answer certified as teaching signal for the others)
```

### A paraphrase the neural reader gets

```text
Q #4253: Which is lower, 36 or -29?  (hidden type: smaller)
  parser    bids p=0.85 (calibrated 0.74), needs 0.0 more compute
  reader    bids p=0.98 (calibrated 0.97), needs 0.0 more compute
  -> reader leads: -29  conf 0.97  because min(n1, n2)  [reads like it, p=0.81, ensemble agrees]
     reader asks checker for review -> endorses: passes whole-number   (belief 0.89 -> 0.90)
  => answers -29 from reader (belief 0.90)  [truth -29: correct]  compute 0.8
     (unlabeled task: answer certified as teaching signal for the others)
```

### Stuck, so it abstains and asks the teacher

```text
Q #4275: How many days are in 17.5 weeks?  (hidden type: unit_up)
  parser    declines: looked, unlikely to help (p~0.14, sampled 0.07)
  reader    bids p=0.70 (calibrated 0.51), needs 0.0 more compute
  -> reader leads: 122.5  conf 0.51  because (n1 * 7)  [reads like it, p=0.41, ensemble split]
     reader asks checker for review -> abstains: no check I trust applies   (belief 0.31 -> 0.31)
  => council abstains (no answer it believes enough)   [truth 122.5]
```

### Peers disagree; the council works it out

```text
Q #4971: Each of 16 boxes holds 3 buttons. How many buttons are there in total?  (hidden type: story_mul)
  parser    bids p=0.91 (calibrated 0.73), needs 0.0 more compute
  reader    bids p=1.00 (calibrated 0.99), needs 0.0 more compute
  -> parser leads: 48  conf 0.73  because (n1 * n2)  [like 'each of # boxes holds # stamps how many stamps are there in total' (0.70); cues: 'holds'->mul]
     parser asks checker for review -> endorses: passes whole-number   (belief 0.77 -> 0.83)
     parser asks estimator for review -> REJECTS: wrong ballpark: I'd expect about 700   (belief 0.83 -> 0.79)
  => answers 48 from parser (belief 0.79)  [truth 48: correct]  compute 4.5
```

