# Synod - 40-question maths exam

Hand-written questions on curriculum topics: new numbers throughout, many in phrasings never seen in training, some with numbers outside the training ranges. The council was trained on the 4000-question curriculum only (no teacher), then frozen for the exam.

## Score: 34/40 right, 4 wrong, 2 abstained

- Familiar wording (new numbers): 22/22 right, 0 wrong
- New wording: 12/18 right, 4 wrong

Same exam, other set-ups (each trained the same way):

| set-up | right | wrong | abstained |
|---|---|---|---|
| parser alone (symbolic) | 31 | 2 | 7 |
| reader alone (neural) | 34 | 4 | 2 |
| hand-written gate | 34 | 5 | 1 |

## Every question

| # | topic | wording | question | key | Synod said | |
|---|---|---|---|---|---|---|
| 1 | arithmetic | familiar | What is 348 plus 279? | 627 | 627 | ✅ |
| 2 | arithmetic | new | Find the difference between 900 and 456. | 444 | 1356 | ❌ |
| 3 | arithmetic | new | What is 64 multiplied by 25? | 1600 | — | 🤷 abstained |
| 4 | arithmetic | new | How much is 144 divided by 12? | 12 | 12 | ✅ |
| 5 | arithmetic | familiar | What is 12 * (7 + 8) - 30? | 150 | 150 | ✅ |
| 6 | remainders | familiar | What is the remainder when 523 is divided by 9? | 1 | 1 | ✅ |
| 7 | remainders | new | When 250 is divided by 7, what is the remainder? | 5 | 5 | ✅ |
| 8 | gcd / lcm | familiar | What is the greatest common divisor of 252 and 198? | 18 | 18 | ✅ |
| 9 | gcd / lcm | new | Find the highest common factor of 91 and 65. | 13 | 13 | ✅ |
| 10 | gcd / lcm | new | What is the smallest number that is a multiple of both 9 and 15? | 45 | 45 | ✅ |
| 11 | primes | familiar | Is 391 a prime number? | 0 | 0 | ✅ |
| 12 | primes | new | Tell me whether 211 is prime. | 1 | 1 | ✅ |
| 13 | powers / roots | familiar | What is 3 to the power of 7? | 2187 | 2187 | ✅ |
| 14 | powers / roots | familiar | What is 45 squared? | 2025 | 2025 | ✅ |
| 15 | powers / roots | familiar | What is the square root of 2209? | 47 | 47 | ✅ |
| 16 | equations | familiar | Solve 7*x - 12 = 23 for x. | 5 | 5 | ✅ |
| 17 | equations | familiar | What is y in 4*y + 9 = 2*y - 7? | -8 | -8 | ✅ |
| 18 | equations | new | If 3*m + 15 = 0, what is m? | -5 | -5 | ✅ |
| 19 | functions | familiar | Let g(x) = 3*x^2 - 2*x + 4. What is g(3)? | 25 | 25 | ✅ |
| 20 | functions | familiar | What is the value of 2*t^3 - t when t = 2? | 14 | 14 | ✅ |
| 21 | derivatives | familiar | Let h(x) = x^3 - 5*x^2 + 2*x. What is the derivative of h at x = 4? | 10 | 10 | ✅ |
| 22 | derivatives | familiar | Differentiate 6*k^2 + 3*k - 1 with respect to k and evaluate at k = -2. | -21 | -21 | ✅ |
| 23 | sequences | familiar | What comes next: 5, 11, 17, 23, 29, 35? | 41 | 41 | ✅ |
| 24 | sequences | familiar | What is the next term in 3, 6, 12, 24, 48, 96? | 192 | 192 | ✅ |
| 25 | sequences | new | Give the next number: 1, 1, 2, 3, 5, 8. | 13 | 13 | ✅ |
| 26 | statistics | familiar | What is the mean of 12, 18, 25, 33 and 37? | 25 | 25 | ✅ |
| 27 | statistics | familiar | What is the median of 7, 3, 19, 11 and 5? | 7 | 7 | ✅ |
| 28 | statistics | new | What is the biggest of 14, -3, 27, 8 and 19? | 27 | 27 | ✅ |
| 29 | comparisons | familiar | Which is bigger: -12 or -15? | -12 | -12 | ✅ |
| 30 | comparisons | new | Is 45 more than 54? | 0 | 0 | ✅ |
| 31 | units | familiar | How many minutes are there in 2.5 hours? | 150 | 150 | ✅ |
| 32 | units | new | How many centimeters make 7 meters? | 700 | — | 🤷 abstained |
| 33 | units | familiar | How many weeks are there in 63 days? | 9 | 9 | ✅ |
| 34 | word problems | new | Leila has 23 stickers. She gets 15 more. How many stickers does Leila have now? | 38 | 38 | ✅ |
| 35 | word problems | new | A baker puts 48 rolls into 6 equal trays. How many rolls are in each tray? | 8 | 8 | ✅ |
| 36 | word problems | new | There are 7 shelves with 9 books on each shelf. How many books are there altogether? | 63 | 63 | ✅ |
| 37 | two-step | familiar | Suppose 5*x - 3 = 22. What is x plus 10? | 15 | 15 | ✅ |
| 38 | two-step | new | Suppose 2*k + 1 = 15. What is k times 3? | 21 | 10 | ❌ |
| 39 | two-step | new | Let f(x) = 2*x + 5. What is f(3) plus 4? | 15 | 44 | ❌ |
| 40 | two-step | new | What is the least common multiple of 4 and 6, minus 5? | 7 | 12 | ❌ |

## Deliberations worth reading

```text
Q #900001: Find the difference between 900 and 456.
  parser    bids p=0.82 (calibrated 0.82), needs 0.0 more compute
  reader    bids p=0.93 (calibrated 0.93), needs 0.0 more compute
  -> reader leads: 1356  conf 0.93  because (n1 + n2)  [reads like it, p=0.92, ensemble agrees, never seen this combination]
     reader asks checker for review -> endorses: passes whole-number   (belief 0.89 -> 0.93)
     reader asks estimator for review -> endorses: right ballpark (I'd guess about 103)   (belief 0.93 -> 0.94)
  => answers 1356 from reader (belief 0.94)  [truth 444: WRONG]  compute 1.5
```

```text
Q #900002: What is 64 multiplied by 25?
  parser    declines: looked, unlikely to help (p~0.34, sampled 0.34)
  reader    bids p=0.68 (calibrated 0.68), needs 0.0 more compute
  => council abstains (no answer it believes enough)   [truth 1600]
```

```text
Q #900031: How many centimeters make 7 meters?
  parser    declines: looked, unlikely to help (p~0.05, sampled 0.05)
  reader    declines: looked, unlikely to help (p~0.26, sampled 0.26)
  => council abstains (no answer it believes enough)   [truth 700]
```

```text
Q #900037: Suppose 2*k + 1 = 15. What is k times 3?
  parser    declines: looked, unlikely to help (p~0.48, sampled 0.48)
  reader    bids p=0.86 (calibrated 0.86), needs 0.0 more compute
  -> reader leads: 10  conf 0.86  because (solve(equation) + n1)  [reads like it, p=0.93, ensemble agrees, never seen this combination]
     reader asks estimator for review -> endorses: right ballpark (I'd guess about 26.7)   (belief 0.63 -> 0.68)
     reader asks checker for review -> endorses: passes whole-number   (belief 0.68 -> 0.72)
  => answers 10 from reader (belief 0.72)  [truth 21: WRONG]  compute 1.5
```

```text
Q #900038: Let f(x) = 2*x + 5. What is f(3) plus 4?
  parser    declines: looked, unlikely to help (p~0.48, sampled 0.48)
  reader    bids p=0.86 (calibrated 0.86), needs 0.0 more compute
  -> reader leads: 44  conf 0.86  because (f(call) * n1)  [reads like it, p=0.87, ensemble agrees, never seen this combination]
     reader asks estimator for review -> endorses: right ballpark (I'd guess about 0.784)   (belief 0.63 -> 0.68)
     reader asks checker for review -> endorses: passes whole-number   (belief 0.68 -> 0.72)
  => answers 44 from reader (belief 0.72)  [truth 15: WRONG]  compute 1.5
```

```text
Q #900039: What is the least common multiple of 4 and 6, minus 5?
  parser    declines: looked, unlikely to help (p~0.25, sampled 0.25)
  reader    bids p=0.86 (calibrated 0.86), needs 0.0 more compute
  -> reader leads: 12  conf 0.86  because lcm(n1, n2)  [reads like it, p=0.95, ensemble agrees, never seen this combination]
     reader asks estimator for review -> endorses: right ballpark (I'd guess about 0.0132)   (belief 0.63 -> 0.69)
     reader asks checker for review -> endorses: passes whole-number   (belief 0.69 -> 0.72)
  => answers 12 from reader (belief 0.72)  [truth 7: WRONG]  compute 4.5
```

```text
Q #900003: How much is 144 divided by 12?
  parser    declines: looked, unlikely to help (p~0.43, sampled 0.43)
  reader    bids p=0.84 (calibrated 0.84), needs 0.0 more compute
  -> reader leads: 12  conf 0.84  because (n1 / n2)  [reads like it, p=0.99, ensemble agrees, never seen this combination]
     reader asks checker for review -> endorses: passes whole-number   (belief 0.62 -> 0.70)
     reader asks estimator for review -> abstains: never seen questions like this; no feel for the size   (belief 0.70 -> 0.70)
  => answers 12 from reader (belief 0.70)  [truth 12: correct]  compute 4.5
```

```text
Q #900006: When 250 is divided by 7, what is the remainder?
  parser    bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  reader    bids p=0.99 (calibrated 0.99), needs 0.0 more compute
  -> parser leads: 5  conf 0.99  because mod(n1, n2)  [like 'what is the remainder when # is divided by #' (1.00); cues: 'remainder'->mod]
     parser asks checker for review -> endorses: passes whole-number   (belief 0.99 -> 0.99)
  => answers 5 from parser (belief 0.99)  [truth 5: correct]  compute 1.2
```

```text
Q #900008: Find the highest common factor of 91 and 65.
  parser    bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  reader    bids p=0.94 (calibrated 0.94), needs 0.0 more compute
  -> parser leads: 13  conf 0.99  because gcd(n1, n2)  [like 'calculate the highest common factor of # and #' (0.72); cues: 'factor'->gcd]
     parser asks reader for review -> endorses: reads it the same way (gcd(n1, n2))   (belief 0.99 -> 0.99)
  => answers 13 from parser (belief 0.99)  [truth 13: correct]  compute 1.1
```

```text
Q #900009: What is the smallest number that is a multiple of both 9 and 15?
  parser    declines: looked, unlikely to help (p~0.34, sampled 0.34)
  reader    bids p=0.98 (calibrated 0.98), needs 0.0 more compute
  -> reader leads: 45  conf 0.98  because lcm(n1, n2)  [reads like it, p=0.88, ensemble agrees, never seen this combination]
     reader asks checker for review -> endorses: passes whole-number   (belief 0.91 -> 0.93)
  => answers 45 from reader (belief 0.93)  [truth 45: correct]  compute 4.2
```

_Exam run took 88s._
