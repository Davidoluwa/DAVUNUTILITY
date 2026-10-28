# Synod - run report

Scenario: 1600 tasks, 35% of them labeled after the fact. Scheduled trouble:

- t=550: neural memory index corrupted (confidently wrong)
- t=1000: new family appears: interleaved sequences
- t=1250: bug in symbolic evaluator (+1 offset)
- t=1400: operator ships a hotfix

Averaged over 10 seeds. Utility per task = +1 correct, -1 wrong, 0 abstain, minus 0.02 per unit of compute.

## Head to head

| strategy | utility | accuracy | wrong answers | abstained | compute/task | utility right after memory fault | utility right after symbolic bug |
|---|---|---|---|---|---|---|---|
| synod | +0.662 ± 0.031 | 84% | 11% | 5% | 3.22 | +0.67 (11% wrong) | +0.23 (30% wrong) |
| neural-only | +0.082 ± 0.038 | 19% | 8% | 73% | 1.50 | +0.10 (6% wrong) | +0.14 (11% wrong) |
| symbolic-only | +0.633 ± 0.021 | 73% | 6% | 20% | 1.85 | +0.69 (5% wrong) | -0.05 (11% wrong) |
| hand-written gate | +0.513 ± 0.024 | 62% | 9% | 29% | 1.05 | +0.49 (8% wrong) | -0.02 (20% wrong) |
| synod w/o task features | +0.647 ± 0.034 | 84% | 11% | 5% | 3.91 | +0.64 (12% wrong) | +0.26 (28% wrong) |
| synod w/o reviewers | **+0.664** ± 0.031 | 84% | 12% | 4% | 3.09 | +0.68 (11% wrong) | +0.25 (28% wrong) |
| synod w/o exchange | +0.649 ± 0.026 | 83% | 11% | 6% | 3.29 | +0.61 (14% wrong) | +0.18 (27% wrong) |
| synod w/o self-healing | +0.620 ± 0.030 | 81% | 12% | 7% | 3.52 | +0.58 (15% wrong) | -0.11 (39% wrong) |

Utility per 100-task window (seed mean):

| window | synod | symbolic-only | hand-written gate | synod w/o self-healing |
|---|---|---|---|---|
| 0-99 | +0.47 | +0.56 | +0.41 | +0.48 |
| 100-199 | +0.59 | +0.67 | +0.48 | +0.60 |
| 200-299 | +0.68 | +0.69 | +0.47 | +0.67 |
| 300-399 | +0.65 | +0.69 | +0.49 | +0.67 |
| 400-499 | +0.70 | +0.72 | +0.53 | +0.70 |
| 500-599 | +0.70 | +0.71 | +0.54 | +0.66 |
| 600-699 | +0.70 | +0.73 | +0.56 | +0.72 |
| 700-799 | +0.69 | +0.68 | +0.54 | +0.68 |
| 800-899 | +0.71 | +0.72 | +0.56 | +0.70 |
| 900-999 | +0.76 | +0.75 | +0.61 | +0.72 |
| 1000-1099 | +0.74 | +0.74 | +0.63 | +0.74 |
| 1100-1199 | +0.77 | +0.74 | +0.67 | +0.76 |
| 1200-1299 | +0.50 | +0.35 | +0.32 | +0.31 |
| 1300-1399 | +0.49 | +0.00 | +0.11 | +0.12 |
| 1400-1499 | +0.64 | +0.61 | +0.58 | +0.61 |
| 1500-1599 | +0.81 | +0.77 | +0.71 | +0.78 |

## Who ended up doing what (seed 0) - emergent, never programmed

Share of delivered answers per hidden family. Nodes never see the family.

| family | t 300-549 (warmed up) | t 1450-1599 (after faults and shift) |
|---|---|---|
| affine | inducer 100% | inducer 100% |
| arithmetic | inducer 100% | inducer 100% |
| fibonacci | inducer 100% | inducer 100% |
| geometric | inducer 100% | inducer 100% |
| interleaved | - | inducer 100% |
| noisy_trend | inducer 68%, recall 17%, intuition 15% | inducer 96%, intuition 4% |
| quadratic | inducer 100% | inducer 100% |
| saturating | recall 64%, intuition 21%, inducer 15% | intuition 87%, recall 9%, inducer 4% |
| wave | inducer 47%, intuition 33%, recall 12%, abstain 9% | inducer 81%, intuition 12%, recall 8% |

## What the nodes decided on their own (seed 0)

- t=550 **world**: neural memory index corrupted (confidently wrong)
- t=552 **intuition**: retracted 14 lessons learned from recall
- t=552 **recall**: audit requested by intuition -> self-test failed (accuracy down 52%): repaired itself, now on probation
- t=602 **recall**: probation complete: back in service
- t=1000 **world**: new family appears: interleaved sequences
- t=1250 **world**: bug in symbolic evaluator (+1 offset)
- t=1273 **inducer**: surprised by a miss at 99% confidence -> self-test failed (accuracy down 58%): cannot self-repair, quarantined itself
- t=1273 **intuition**: retracted 25 lessons learned from inducer
- t=1273 **recall**: retracted 64 lessons learned from inducer
- t=1400 **world**: operator ships a hotfix
- t=1422 **inducer**: self-test passed (accuracy drop 0%): leaving quarantine on probation
- t=1451 **inducer**: probation complete: back in service

Self-checks that came back clean (false alarms, cost only maintenance compute): intuition 1, recall 3, inducer 3.

## What the symbolic side learned (seed 0)

Concepts the inducer invented (laws confirmed often enough to be checked first, almost for free):

- `x[n] = x[n-1] + x[n-2]` (confirmed 90x)
- `x[n] = 4*x[n-1] - 3*x[n-2]` (confirmed 72x)
- `x[n] = 2*x[n-1] - x[n-2]` (confirmed 51x)
- `x[n] = 3*x[n-1] - 2*x[n-2]` (confirmed 44x)
- `x[n] = -1.6*x[n-1] + 0.8*x[n-2]` (confirmed 30x)
- `x[n] = x[n-2] + 9` (confirmed 4x)
- `x[n] = x[n-2] - 1` (confirmed 4x)
- `x[n] = x[n-2] + 6` (confirmed 4x)

Situations where it learned exact laws never turn up, so it stopped hunting for them and switched to cheap approximate laws:

- loose / real / smooth / steady
- loose / real / rough / steady
- loose / real / smooth / decaying
- loose / real / rough / explosive
- loose / real / smooth / explosive
- loose / real / rough / decaying
- tight / real / rough / steady

Critic's learned trust in its own constraints (how often reality respected each one):

- keeps-direction: 99% (evidence 170)
- keeps-curvature: 94% (evidence 125)
- bounded-step: 100% (evidence 189)
- constant-growth-ratio: 95% (evidence 112)
- stays-in-envelope: 73% (evidence 73)

## What the critic reported (seed 0)

The critic reports signals on every candidate; the judge learns what they're worth.

| reviewer | signal | candidate was | count |
|---|---|---|---|
| critic | a trusted one broken | candidate right | 11 |
| critic | a trusted one broken | candidate wrong | 63 |
| critic | all trusted kept | candidate right | 662 |
| critic | all trusted kept | candidate wrong | 200 |

## Sample deliberations (seed 0, auto-picked)

### A symbolic law the judge trusts on sight

```text
task #301  [0, 4, 12, 28, 60, 124, 252, 508, ?]  tolerance ±0.5  (hidden family: affine)
  intuition not consulted (router: 18% chance of being right here; a second opinion isn't worth its compute)
  critic    not consulted (router: its opinion here is worth +0.005, less than its compute (0.008))
  inducer   consulted (router 96%): 1020  self-confidence 0.99  gate 0.99  because x[n] = 3*x[n-1] - 2*x[n-2]  (concept recurrence-2[3.0, -2.0])
  recall    consulted (router 75%): 1020  self-confidence 0.99  gate 0.00  because recalls exact match -> 1020.00
  judge: 1020 ← inducer+recall: 1.00   none of these: 0.00   (deliver at ≥ 0.50)
     why it trusted inducer: +0.5 e|inducer|exact, +0.5 x|inducer|ctx:int, +0.5 x|inducer|ctx:tight, +0.4 with|inducer|recall
  => answers 1020 from inducer (probability 1.00)  [truth 1020: correct]  compute 0.7
     (confident enough to teach the members from this answer)
```

### The router skips a member that rarely helps here

```text
task #300  [13, 38, 65, 94, 125, 158, 193, 230, ?]  tolerance ±0.5  (hidden family: quadratic)
  intuition not consulted (router: 28% chance of being right here; a second opinion isn't worth its compute)
  critic    not consulted (router: its opinion here is worth -0.012, less than its compute (0.016))
  inducer   consulted (router 97%): 269  self-confidence 0.99  gate 0.94  because x[n] = 13 + 24*n^1 + n^2
  recall    consulted (router 76%): 266.4  self-confidence 0.01  gate 0.05  because recalls mid match -> 266.39
  judge: 266.4 ← recall: 0.05  269 ← inducer: 0.94   none of these: 0.00   (deliver at ≥ 0.50)
     why it trusted inducer: +0.5 e|inducer|exact, +0.5 x|inducer|ctx:int, +0.5 x|inducer|ctx:tight, +0.3 cl|inducer
  => answers 269 from inducer (probability 0.94)  [truth 269: correct]  compute 1.6
```

### Neural intuition handles a noisy nonlinear series

```text
task #430  [9.077, 4.968, -2.628, -11.55, -17.66, -21.05, -20.14, -16.53, ?]  tolerance ±3.3  (hidden family: wave)
  intuition consulted (router 71%): -7.929  self-confidence 0.74  gate 0.52  because ensemble says -7.93 ± 3.97
  recall    consulted (router 67%): -8.006  self-confidence 0.43  gate 0.10  because recalls far match -> -8.01
  inducer   consulted (router 66%): -11.74  self-confidence 0.82  gate 0.30  because ~x[n] = 1.51*x[n-1] - 0.804*x[n-2] - 3.05  (best approximate law, sd 1.07)
     critic on -11.74: keeps-curvature kept:weak, bounded-step kept:trusted
     critic on -8.006: keeps-curvature kept:weak, bounded-step kept:trusted
  judge: -11.74 ← inducer: 0.30  -8.006 ← recall+intuition: 0.62   none of these: 0.08   (deliver at ≥ 0.50)
     why it trusted intuition: −0.5 with|intuition|recall|m/far, +0.3 v|intuition|critic|endorse, +0.2 ex|intuition|n5/c2|ctx:smooth, +0.2 e|intuition|n5/c2
  => answers -7.929 from intuition (probability 0.62)  [truth -9.543: correct]  compute 4.9
```

### Members disagree; the judge picks the right one

```text
task #307  [10.06, 10.09, 10.61, 12.02, 17.1, 26.99, 41.28, 51.36, ?]  tolerance ±1.9  (hidden family: saturating)
  critic    not consulted (router: its opinion here is worth -0.040, less than its compute (0.016))
  recall    consulted (router 72%): 57.43  self-confidence 0.55  gate 0.88  because recalls far match -> 57.43
  intuition consulted (router 66%): 56.5  self-confidence 0.62  gate 0.05  because ensemble says 56.50 ± 7.84
  inducer   consulted (router 56%): 68.33  self-confidence 0.00  gate 0.02  because ~x[n] = 1.33*x[n-1]  (best approximate law, sd 5.05)
  judge: 56.5 ← intuition+recall: 0.93  68.33 ← inducer: 0.02   none of these: 0.05   (deliver at ≥ 0.50)
     why it trusted recall: +0.3 vs|recall|inducer|approx/c1, +0.3 ag|recall|1, +0.2 with|recall|intuition, +0.2 e|recall|m/far/split
  => answers 57.43 from recall (probability 0.93)  [truth 55.8: correct]  compute 3.6
```

### Honest abstention instead of a wrong answer

```text
task #601  [-6.591, -3.676, 1.849, 13.1, 22.92, 25.32, 27.28, 27.68, ?]  tolerance ±1.4  (hidden family: saturating)
  inducer   consulted (router 66%): 32.58  self-confidence 0.07  gate 0.18  because ~x[n] = x[n-1] + 4.9  (best approximate law, sd 4.45)
  intuition consulted (router 63%): 26.18  self-confidence 0.62  gate 0.12  because ensemble says 26.18 ± 3.67
     critic on 26.18: keeps-direction broken:trusted, keeps-curvature kept:weak, bounded-step kept:trusted
     critic on 32.58: keeps-direction kept:trusted, keeps-curvature broken:weak, bounded-step kept:trusted
  judge: 26.18 ← intuition: 0.12  32.58 ← inducer: 0.18   none of these: 0.70   (deliver at ≥ 0.50)
     why it held back: −0.3 nc|null|2, −0.2 null, −0.2 x|null|ctx:smooth, +0.1 has|null|inducer|approx/c1
  => council abstains   [truth 27.72]
```

### Inducer quarantined: the others cover what they can

```text
task #1287  [15, 16, 17, 18, 19, 20, 21, 22, ?]  tolerance ±0.5  (hidden family: arithmetic)
  critic    not consulted (router: its opinion here is worth -0.008, less than its compute (0.008))
  recall    consulted (router 84%): 23  self-confidence 0.99  gate 0.81  because recalls exact match -> 23.00
  intuition consulted (router 57%): 23.01  self-confidence 0.76  gate 0.17  because ensemble says 23.01 ± 0.81
  judge: 23 ← recall+intuition: 0.98   none of these: 0.02   (deliver at ≥ 0.50)
     why it trusted recall: +0.3 x|recall|ctx:smooth, +0.2 with|recall|intuition, +0.2 e|recall|m/exact, +0.2 e|recall|m/exact/agree
  => answers 23 from recall (probability 0.98)  [truth 23: correct]  compute 2.0
     (confident enough to teach the members from this answer)
```

