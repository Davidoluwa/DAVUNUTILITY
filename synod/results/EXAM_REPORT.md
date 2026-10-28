# Synod - 40-question maths exam

Hand-written questions on curriculum topics: new numbers throughout, many in phrasings never seen in training, some with numbers outside the training ranges. The council was trained on the 4000-question curriculum only (no teacher), then frozen for the exam.

## Score: 37/40 right, 3 wrong, 0 abstained

- Familiar wording (new numbers): 22/22 right, 0 wrong
- New wording: 15/18 right, 3 wrong

Same exam, other set-ups (each trained the same way):

| set-up | right | wrong | abstained |
|---|---|---|---|
| parser alone (symbolic) | 31 | 2 | 7 |
| reader alone (neural) | 34 | 4 | 2 |
| hand-written gate | 34 | 3 | 3 |

## Every question

| # | topic | wording | question | key | Synod said | |
|---|---|---|---|---|---|---|
| 1 | arithmetic | familiar | What is 348 plus 279? | 627 | 627 | ✅ |
| 2 | arithmetic | new | Find the difference between 900 and 456. | 444 | -444 | ❌ |
| 3 | arithmetic | new | What is 64 multiplied by 25? | 1600 | 1600 | ✅ |
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
| 32 | units | new | How many centimeters make 7 meters? | 700 | 700 | ✅ |
| 33 | units | familiar | How many weeks are there in 63 days? | 9 | 9 | ✅ |
| 34 | word problems | new | Leila has 23 stickers. She gets 15 more. How many stickers does Leila have now? | 38 | 38 | ✅ |
| 35 | word problems | new | A baker puts 48 rolls into 6 equal trays. How many rolls are in each tray? | 8 | 0 | ❌ |
| 36 | word problems | new | There are 7 shelves with 9 books on each shelf. How many books are there altogether? | 63 | 63 | ✅ |
| 37 | two-step | familiar | Suppose 5*x - 3 = 22. What is x plus 10? | 15 | 15 | ✅ |
| 38 | two-step | new | Suppose 2*k + 1 = 15. What is k times 3? | 21 | 21 | ✅ |
| 39 | two-step | new | Let f(x) = 2*x + 5. What is f(3) plus 4? | 15 | 15 | ✅ |
| 40 | two-step | new | What is the least common multiple of 4 and 6, minus 5? | 7 | 10 | ❌ |

## Deliberations worth reading

```text
Q #900001: Find the difference between 900 and 456.
  estimator not consulted (router: its opinion here is worth +0.000, less than its compute (0.012))
  reader    consulted (router 99%): 1356  self-confidence 0.97  gate 0.48  because (n1 + n2)  [reads like it, p=0.98, ensemble agrees, never seen this combination]
  parser    consulted (router 99%): -444  self-confidence 0.85  gate 0.52  because (n2 - n1)  [like 'find the difference when # is subtracted from #' (0.37); cues: 'difference'->sub:rev]
     checker on -444: whole-number pass:trusted, yes-or-no fail:weak
     checker on 1356: whole-number pass:trusted, yes-or-no fail:weak
  judge: -444 ← parser: 0.52  1356 ← reader: 0.48   none of these: 0.01   (deliver at ≥ 0.50)
     why it trusted parser: +0.6 v|parser|checker|endorse, +0.6 v|parser|checker|whole-number:pass:trusted, +0.5 ex|parser|analogy/far|ctx:medium, +0.3 ag|parser|0
  => answers -444 from parser (probability 0.52)  [truth 444: WRONG]  compute 1.3
```

```text
Q #900034: A baker puts 48 rolls into 6 equal trays. How many rolls are in each tray?
  reader    not consulted (router: 100% chance of being right here; a second opinion isn't worth its compute)
  estimator not consulted (router: its opinion here is worth +0.000, less than its compute (0.006))
  checker   not consulted (router: its opinion here is worth -0.034, less than its compute (0.002))
  parser    consulted (router 100%): 0  self-confidence 0.41  gate 0.97  because (is_prime(n1) / n2)  [composed from word meanings; cues: 'puts'->div, 'a'->is_prime]
  judge: 0 ← parser: 0.97   none of these: 0.03   (deliver at ≥ 0.50)
     why it trusted parser: −0.5 ex|parser|lexical/none|w:#, −0.5 ex|parser|lexical/none|w:in, +0.4 x|parser|ctx:multi, +0.3 ag|parser|0
  => answers 0 from parser (probability 0.97)  [truth 8: WRONG]  compute 3.6
```

```text
Q #900039: What is the least common multiple of 4 and 6, minus 5?
  reader    not consulted (router: 100% chance of being right here; a second opinion isn't worth its compute)
  estimator not consulted (router: its opinion here is worth +0.000, less than its compute (0.006))
  checker   not consulted (router: its opinion here is worth -0.042, less than its compute (0.002))
  parser    consulted (router 100%): 10  self-confidence 0.13  gate 0.95  because lcm((n1 - n2), n3)  [composed from word meanings; cues: 'multiple'->lcm, 'minus'->sub]
  judge: 10 ← parser: 0.95   none of these: 0.05   (deliver at ≥ 0.50)
     why it trusted parser: −0.5 ex|parser|lexical/none|w:#, +0.4 x|parser|w:what, −0.3 x|parser|w:common, +0.3 ag|parser|0
  => answers 10 from parser (probability 0.95)  [truth 7: WRONG]  compute 3.6
```

```text
Q #900002: What is 64 multiplied by 25?
  reader    not consulted (router: 100% chance of being right here; a second opinion isn't worth its compute)
  estimator not consulted (router: its opinion here is worth +0.000, less than its compute (0.006))
  checker   not consulted (router: its opinion here is worth -0.036, less than its compute (0.002))
  parser    consulted (router 100%): 1600  self-confidence 0.29  gate 0.97  because (n1 * n2)  [like 'calculate # multiplied by #' (0.54); cues: 'multiplied'->mul]
  judge: 1600 ← parser: 0.97   none of these: 0.03   (deliver at ≥ 0.50)
     why it trusted parser: +0.4 x|parser|w:what, +0.4 ex|parser|analogy/far|w:what, −0.4 ex|parser|analogy/far|ctx:small, +0.3 ag|parser|0
  => answers 1600 from parser (probability 0.97)  [truth 1600: correct]  compute 0.6
```

```text
Q #900003: How much is 144 divided by 12?
  reader    not consulted (router: 100% chance of being right here; a second opinion isn't worth its compute)
  estimator not consulted (router: its opinion here is worth +0.000, less than its compute (0.006))
  checker   not consulted (router: its opinion here is worth -0.001, less than its compute (0.002))
  parser    consulted (router 100%): 12  self-confidence 0.41  gate 0.98  because (n1 / n2)  [like 'what is # divided by #' (0.54); cues: 'divided'->div]
  judge: 12 ← parser: 0.98   none of these: 0.02   (deliver at ≥ 0.50)
     why it trusted parser: +0.5 ex|parser|analogy/far|ctx:medium, +0.3 ag|parser|0, +0.3 b|parser, +0.3 nc|parser|1
  => answers 12 from parser (probability 0.98)  [truth 12: correct]  compute 3.6
```

```text
Q #900006: When 250 is divided by 7, what is the remainder?
  reader    not consulted (router: 100% chance of being right here; a second opinion isn't worth its compute)
  estimator not consulted (router: its opinion here is worth +0.000, less than its compute (0.006))
  checker   not consulted (router: its opinion here is worth -0.023, less than its compute (0.002))
  parser    consulted (router 100%): 5  self-confidence 0.99  gate 0.99  because mod(n1, n2)  [like 'what is the remainder when # is divided by #' (1.00); cues: 'remainder'->mod]
  judge: 5 ← parser: 0.99   none of these: 0.01   (deliver at ≥ 0.50)
     why it trusted parser: +0.8 cb|parser|9, −0.7 ex|parser|analogy/near|ctx:single, +0.6 ex|parser|analogy/near|ctx:N2, +0.5 cl|parser
  => answers 5 from parser (probability 0.99)  [truth 5: correct]  compute 0.6
```

```text
Q #900008: Find the highest common factor of 91 and 65.
  estimator not consulted (router: its opinion here is worth +0.000, less than its compute (0.006))
  checker   not consulted (router: its opinion here is worth -0.050, less than its compute (0.002))
  parser    consulted (router 99%): 13  self-confidence 0.99  gate 0.19  because gcd(n1, n2)  [like 'calculate the highest common factor of # and #' (0.72); cues: 'factor'->gcd]
  reader    consulted (router 99%): 13  self-confidence 0.99  gate 0.78  because gcd(n1, n2)  [reads like it, p=0.95, ensemble agrees]
  judge: 13 ← parser+reader: 0.97   none of these: 0.03   (deliver at ≥ 0.50)
     why it trusted reader: +0.5 cl|reader, +0.5 cb|reader|9, +0.3 nc|reader|1, +0.3 ex|reader|r/familiar|ctx:small
  => answers 13 from reader (probability 0.97)  [truth 13: correct]  compute 1.1
```

_Exam run took 77s._
