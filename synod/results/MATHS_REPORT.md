# Synod does maths - run report

Nobody tells the system what any wording means. It gets 4000 practice questions (half with the answer revealed afterwards), then five test sets with **no answers at all**. The teacher variant may ask for the answer to questions it couldn't settle, after answering them, up to a small budget.

Averaged over 10 seeds.

## Accuracy on each test set (wrong answers in brackets; the rest are abstentions)

| strategy | seen | paraphrase | big | story | compose |
|---|---|---|---|---|---|
| synod (frozen after training) | 100% (0%) | 85% (6%) | 100% (0%) | 93% (4%) | 64% (29%) |
| parser alone (symbolic) | 100% (0%) | 70% (5%) | 100% (0%) | 76% (0%) | 44% (0%) |
| reader alone (neural) | 98% (0%) | 81% (9%) | 97% (0%) | 61% (10%) | 1% (80%) |
| hand-written gate | 100% (0%) | 67% (7%) | 99% (0%) | 56% (7%) | 1% (72%) |
| synod (keeps learning from its confident answers) | 100% (0%) | 85% (6%) | 100% (0%) | 89% (7%) | 64% (31%) |
| synod + teacher (asks ≤40) | 100% (0%) | 84% (6%) | 100% (0%) | 94% (4%) | 61% (37%) |

- **seen**: familiar wording, new numbers
- **paraphrase**: wording never seen in training
- **big**: numbers ~100x bigger than training
- **story**: word problems: new names, objects, phrasing
- **compose**: two-step combinations never seen

## How much of what its members knew did the council use?

Ceiling = at least one consulted member proposed the right answer. The gap is the judge's to close.

| strategy | seen | paraphrase | big | story | compose |
|---|---|---|---|---|---|
| synod (frozen after training) | 100% of 100% | 85% of 93% | 100% of 100% | 93% of 97% | 64% of 64% |
| synod (keeps learning from its confident answers) | 100% of 100% | 85% of 94% | 100% of 100% | 89% of 93% | 64% of 65% |
| synod + teacher (asks ≤40) | 100% of 100% | 84% of 95% | 100% of 100% | 94% of 96% | 61% of 61% |

The teacher variant asked 40 questions on average (out of 1250 test questions).

Training accuracy per 500 questions (synod): 67%, 95%, 97%, 98%, 99%, 99%, 99%, 100%

## Inside one run (seed 0, with teacher)

- Wordings the parser knows: 548; programs the reader can produce: 102.
- Questions it asked the teacher about, by hidden type: unit_down 3, lmax 3, story_sub 3, lsum 3, mul 3, lmin 3, next 2, at 2, bigger 2, smaller 2, story_mul 2, comp_solve_mod 1, lcm 1, sub 1, calc 1, mod 1, median 1, square 1, gt 1, prime 1, comp_apply_mul 1, sqrt 1, unit_up 1.
- The parser learned 289 new wordings from answers the council was confident enough to teach from.

Who answered each test set:

| test set | answered by |
|---|---|
| seen | parser 79%, reader 21% |
| paraphrase | parser 70%, reader 29%, abstain 1% |
| big | parser 89%, reader 11% |
| story | reader 74%, parser 26% |
| compose | parser 80%, reader 20% |

What the parser thinks words mean (learned, strongest cues per operation):

- `add`: more, gets, now
- `mul`: times, multiplied, altogether
- `solve`: at, suppose, derivative
- `div`: shared, friends, friend
- `sub`: away, gives, left
- `apply`: let, times, define
- `mod`: remainder, modulo, when
- `gcd`: greatest, divisor, factor
- `lcm`: multiple, least, smallest
- `next`: next, comes, sequence
- `lmin`: lowest, smallest, value
- `at`: evaluate, at, value
- `sqrt`: root, square
- `min`: smaller, less, or
- `pow`: power, raised, to
- `slope`: derivative, respect, differentiate
- `lmax`: largest, biggest, value
- `calc`: compute, evaluate
- `median`: median
- `sum`: total
- `square`: squared, square
- `max`: bigger, greater, or
- `mean`: average, mean
- `is_prime`: prime, whether, determine

## Sample deliberations (seed 0, auto-picked)

### Exact on numbers far bigger than anything in training

```text
Q #4501: What is z in 5*z + 500 = 4000?  (hidden type: solve)
  reader    not consulted (router: 100% chance of being right here; a second opinion isn't worth its compute)
  estimator not consulted (router: its opinion here is worth -0.134, less than its compute (0.006))
  checker   not consulted (router: its opinion here is worth -0.101, less than its compute (0.002))
  parser    consulted (router 100%): 700  self-confidence 0.99  gate 1.00  because solve(equation)  [wording seen before (15 confirmations)]
  judge: 700 ← parser: 1.00   none of these: 0.00   (deliver at ≥ 0.50)
     why it trusted parser: +0.7 e|parser|known, +0.6 cl|parser, +0.6 cb|parser|9, +0.6 e|parser|known/5+
  => answers 700 from parser (probability 1.00)  [truth 700: correct]  compute 0.2
     (confident enough to teach the members from this answer)
```

### A word problem with a new name, object and phrasing

```text
Q #4750: Kofi had 29 cards and used 8. How many cards remain?  (hidden type: story_sub)
  reader    consulted (router 100%): 21  self-confidence 0.99  gate 0.91  because (n1 - n2)  [reads like it, p=0.98, ensemble agrees]
  parser    consulted (router 99%): 21  self-confidence 0.99  gate 0.09  because (n1 - n2)  [like 'kofi had # stamps and used # how many stamps remain' (0.69); cues: 'had'->sub]
     estimator on 21: I'd guess about 28.2; this is close (new question)
     checker on 21: whole-number pass:trusted, yes-or-no fail:weak
  judge: 21 ← reader+parser: 1.00   none of these: 0.00   (deliver at ≥ 0.50)
     why it trusted reader: +0.5 cl|reader, +0.4 x|reader|ctx:N2, +0.4 x|reader|ctx:multi, +0.4 cb|reader|9
  => answers 21 from reader (probability 1.00)  [truth 21: correct]  compute 1.5
     (confident enough to teach the members from this answer)
```

### A paraphrase, handled by analogy with a known wording

```text
Q #4268: Find the derivative of -2*x - 2 at x = -5.  (hidden type: slope)
  reader    not consulted (router: 99% chance of being right here; a second opinion isn't worth its compute)
  parser    consulted (router 100%): -2  self-confidence 0.80  gate 0.99  because expr'(solve(equation))  [like 'differentiate <poly> with respect to <var> and evaluate at <eq>' (0.24); cues: 'derivative'->slope, 'at'->solve]
     estimator on -2: I'd guess about -1.75; this is close (familiar question)
     checker on -2: satisfies-the-equation fail:weak, whole-number pass:trusted, yes-or-no fail:weak
  judge: -2 ← parser: 0.99   none of these: 0.01   (deliver at ≥ 0.50)
     why it trusted parser: +0.7 e|parser|analogy/far/clear, +0.3 cb|parser|7, −0.3 ex|parser|analogy/far|w:of, +0.3 v|parser|estimator|endorse
  => answers -2 from parser (probability 0.99)  [truth -2: correct]  compute 1.0
     (confident enough to teach the members from this answer)
```

### A paraphrase the neural reader gets

```text
Q #4250: How many minutes are in 13.5 hours?  (hidden type: unit_up)
  parser    consulted (router 94%): 0.225  self-confidence 0.96  gate 0.05  because (n1 / 60)  [like 'how many hours are there in # minutes' (0.84); cues: 'minutes'->div*60]
  reader    consulted (router 92%): 810  self-confidence 0.99  gate 0.86  because (n1 * 60)  [reads like it, p=0.97, ensemble agrees]
     estimator on 0.225: I'd guess about 34.2; this is loose (familiar question)
     estimator on 810: I'd guess about 34.2; this is loose (familiar question)
     checker on 0.225: yes-or-no fail:weak
     checker on 810: yes-or-no fail:weak
  judge: 0.225 ← parser: 0.05  810 ← reader: 0.86   none of these: 0.09   (deliver at ≥ 0.50)
     why it trusted reader: +0.5 cl|reader, −0.4 x|reader|ctx:N1, +0.4 cb|reader|9, +0.3 ex|reader|r/familiar|ctx:small
  => answers 810 from reader (probability 0.86)  [truth 810: correct]  compute 1.9
```

### A never-seen combination, composed from word meanings

```text
Q #5089: Let f(y) = -y. What is f(-3) plus 7?  (hidden type: comp_apply_add)
  reader    not consulted (router: 100% chance of being right here; a second opinion isn't worth its compute)
  estimator not consulted (router: its opinion here is worth -0.019, less than its compute (0.006))
  checker   not consulted (router: its opinion here is worth -0.028, less than its compute (0.002))
  parser    consulted (router 100%): 10  self-confidence 0.21  gate 0.98  because (f(call) + n1)  [like 'let <fdef> what is <call> times #' (0.67), with one change; cues: 'let'->apply, 'plus'->add]
  judge: 10 ← parser: 0.98   none of these: 0.02   (deliver at ≥ 0.50)
     why it trusted parser: +0.3 x|parser|w:what, +0.3 x|parser|w:is, +0.3 x|parser|ctx:multi, +0.3 ag|parser|0
  => answers 10 from parser (probability 0.98)  [truth 10: correct]  compute 0.6
     (confident enough to teach the members from this answer)
```

### Peers disagree; the council works it out

```text
Q #4011: Convert 16 days to hours.  (hidden type: unit_up)
  parser    consulted (router 89%): 384  self-confidence 0.94  gate 0.99  because (n1 * 24)  [wording seen before (1 confirmations)]
  reader    consulted (router 81%): 2.286  self-confidence 0.77  gate 0.01  because (n1 / 7)  [reads like it, p=0.55, ensemble agrees]
     estimator on 2.286: I'd guess about 5.88; this is close (familiar question)
     estimator on 384: I'd guess about 5.88; this is loose (familiar question)
     checker on 2.286: whole-number fail:trusted, yes-or-no fail:weak
     checker on 384: whole-number pass:trusted, yes-or-no fail:weak
  judge: 2.286 ← reader: 0.01  384 ← parser: 0.99   none of these: 0.00   (deliver at ≥ 0.50)
     why it trusted parser: +0.7 e|parser|known, +0.6 cb|parser|9, +0.4 ex|parser|known/1|ctx:N1, +0.4 cl|parser
  => answers 384 from parser (probability 0.99)  [truth 384: correct]  compute 1.5
     (confident enough to teach the members from this answer)
```

