# Synod - run report

Scenario: 1600 tasks, 35% of them labeled after the fact. Scheduled trouble:

- t=550: neural memory index corrupted (confidently wrong)
- t=1000: new family appears: interleaved sequences
- t=1250: bug in symbolic evaluator (+1 offset)
- t=1400: operator ships a hotfix

Averaged over 5 seeds. Utility per task = +1 correct, -1 wrong, 0 abstain, minus 0.02 per unit of compute.

## Head to head

| strategy | utility | accuracy | wrong answers | abstained | compute/task | utility right after memory fault | utility right after symbolic bug |
|---|---|---|---|---|---|---|---|
| synod | **+0.671** ± 0.055 | 81% | 8% | 11% | 2.50 | +0.64 (8% wrong) | +0.41 (18% wrong) |
| neural-only | +0.085 ± 0.038 | 20% | 9% | 71% | 1.50 | +0.13 (5% wrong) | +0.09 (12% wrong) |
| symbolic-only | +0.631 ± 0.023 | 73% | 6% | 20% | 1.84 | +0.71 (4% wrong) | -0.08 (17% wrong) |
| hand-written gate | +0.522 ± 0.013 | 63% | 9% | 28% | 1.08 | +0.50 (5% wrong) | +0.01 (23% wrong) |
| synod w/o review | +0.660 ± 0.039 | 80% | 10% | 10% | 2.43 | +0.65 (12% wrong) | +0.32 (22% wrong) |
| synod w/o trust | +0.656 ± 0.022 | 80% | 9% | 11% | 2.47 | +0.60 (10% wrong) | +0.35 (19% wrong) |
| synod w/o exchange | +0.648 ± 0.033 | 79% | 9% | 12% | 2.51 | +0.53 (17% wrong) | +0.31 (22% wrong) |
| synod w/o self-healing | +0.551 ± 0.063 | 72% | 11% | 16% | 2.84 | +0.49 (19% wrong) | -0.36 (57% wrong) |

Utility per 100-task window (seed mean):

| window | synod | symbolic-only | hand-written gate | synod w/o self-healing |
|---|---|---|---|---|
| 0-99 | +0.46 | +0.56 | +0.42 | +0.43 |
| 100-199 | +0.62 | +0.65 | +0.49 | +0.59 |
| 200-299 | +0.64 | +0.68 | +0.49 | +0.63 |
| 300-399 | +0.70 | +0.68 | +0.46 | +0.67 |
| 400-499 | +0.72 | +0.74 | +0.56 | +0.72 |
| 500-599 | +0.69 | +0.73 | +0.49 | +0.65 |
| 600-699 | +0.73 | +0.74 | +0.59 | +0.61 |
| 700-799 | +0.65 | +0.65 | +0.53 | +0.63 |
| 800-899 | +0.72 | +0.71 | +0.60 | +0.69 |
| 900-999 | +0.74 | +0.77 | +0.62 | +0.70 |
| 1000-1099 | +0.77 | +0.75 | +0.56 | +0.70 |
| 1100-1199 | +0.77 | +0.73 | +0.70 | +0.74 |
| 1200-1299 | +0.55 | +0.31 | +0.33 | +0.19 |
| 1300-1399 | +0.55 | +0.00 | +0.14 | -0.11 |
| 1400-1499 | +0.59 | +0.60 | +0.63 | +0.34 |
| 1500-1599 | +0.81 | +0.80 | +0.74 | +0.63 |

## Who ended up doing what (seed 0) - emergent, never programmed

Share of delivered answers per hidden family. Nodes never see the family.

| family | t 300-549 (warmed up) | t 1450-1599 (after faults and shift) |
|---|---|---|
| affine | recall 100% | recall 100% |
| arithmetic | recall 100% | recall 100% |
| fibonacci | inducer 96%, recall 4% | inducer 90%, recall 10% |
| geometric | recall 100% | recall 100% |
| interleaved | - | inducer 82%, recall 18% |
| noisy_trend | inducer 80%, intuition 12%, recall 7% | inducer 58%, intuition 21%, recall 17%, abstain 4% |
| quadratic | inducer 81%, recall 19% | inducer 69%, recall 23%, abstain 8% |
| saturating | intuition 44%, inducer 31%, recall 23%, abstain 3% | intuition 70%, recall 26%, inducer 4% |
| wave | inducer 56%, intuition 30%, recall 7%, abstain 7% | intuition 62%, inducer 27%, recall 12% |

## What the nodes decided on their own (seed 0)

- t=550 **world**: neural memory index corrupted (confidently wrong)
- t=559 **intuition**: retracted 9 lessons learned from recall
- t=559 **recall**: surprised by a miss at 99% confidence -> self-test failed (accuracy down 60%): repaired itself, now on probation
- t=607 **recall**: probation complete: back in service
- t=1000 **world**: new family appears: interleaved sequences
- t=1250 **world**: bug in symbolic evaluator (+1 offset)
- t=1277 **inducer**: surprised by a miss at 99% confidence -> self-test failed (accuracy down 68%): cannot self-repair, quarantined itself
- t=1277 **intuition**: retracted 14 lessons learned from inducer
- t=1277 **recall**: retracted 32 lessons learned from inducer
- t=1400 **world**: operator ships a hotfix
- t=1426 **inducer**: self-test passed (accuracy drop 0%): leaving quarantine on probation
- t=1456 **inducer**: probation complete: back in service

Self-checks that came back clean (false alarms, cost only maintenance compute): intuition 2, recall 1, inducer 4.

## What the symbolic side learned (seed 0)

Concepts the inducer invented (laws confirmed often enough to be checked first, almost for free):

- `x[n] = x[n-1] + x[n-2]` (confirmed 80x)
- `x[n] = 2*x[n-1]` (confirmed 9x)
- `x[n] = 3*x[n-1]` (confirmed 8x)
- `x[n] = 3*x[n-1] + 1` (confirmed 4x)
- `x[n] = x[n-2] + 9` (confirmed 4x)
- `x[n] = x[n-2] + 6` (confirmed 4x)
- `x[n] = x[n-2] - 1` (confirmed 4x)

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

## Peer review outcomes (seed 0)

| reviewer | verdict | lead was | count |
|---|---|---|---|
| critic | abstained | lead right | 1 |
| critic | abstained | lead wrong | 1 |
| critic | endorsed | lead right | 118 |
| critic | endorsed | lead wrong | 28 |
| critic | rejected | lead right | 2 |
| critic | rejected | lead wrong | 1 |
| inducer | abstained | lead right | 9 |
| inducer | abstained | lead wrong | 9 |
| inducer | endorsed | lead right | 19 |
| inducer | rejected | lead wrong | 2 |
| intuition | abstained | lead right | 2 |
| intuition | abstained | lead wrong | 2 |
| intuition | endorsed | lead right | 61 |
| intuition | endorsed | lead wrong | 3 |
| intuition | rejected | lead right | 21 |
| intuition | rejected | lead wrong | 18 |
| recall | abstained | lead right | 347 |
| recall | abstained | lead wrong | 87 |
| recall | endorsed | lead right | 64 |
| recall | rejected | lead right | 1 |

## Sample deliberations (seed 0, auto-picked)

### A symbolic law, no review needed

```text
task #313  [-21, 20, -1, 19, 18, 37, 55, 92, ?]  tolerance ±0.5  (hidden family: fibonacci)
  intuition declines: looked, unlikely to help (p~0.04, sampled 0.02)
  recall    bids p=0.74 (calibrated 0.68), needs 0.0 more compute
  inducer   bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  -> inducer leads: 147  conf 0.99  because x[n] = x[n-1] + x[n-2]  (concept recurrence-2[1.0, 1.0])
     inducer skips review (not worth the compute at this confidence)
  => answers 147 from inducer (belief 0.95)  [truth 147: correct]  compute 1.2
```

### Memory covers a known shape; others don't bother looking

```text
task #301  [0, 4, 12, 28, 60, 124, 252, 508, ?]  tolerance ±0.5  (hidden family: affine)
  intuition declines: rarely useful here (p_useful~0.02)
  inducer   declines: already covered by recall (belief 0.99)
  recall    bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  -> recall leads: 1020  conf 0.99  because recalls exact match -> 1020.00
     recall skips review (not worth the compute at this confidence)
  => answers 1020 from recall (belief 0.99)  [truth 1020: correct]  compute 0.5
     (unlabeled task: answer certified as teaching signal for the others)
```

### Neural intuition handles a noisy nonlinear series

```text
task #307  [10.06, 10.09, 10.61, 12.02, 17.1, 26.99, 41.28, 51.36, ?]  tolerance ±1.9  (hidden family: saturating)
  recall    declines: looked, unlikely to help (p~0.31, sampled 0.47)
  inducer   declines: looked, unlikely to help (p~0.27, sampled 0.48)
  intuition bids p=0.97 (calibrated 0.91), needs 0.9 more compute
  -> intuition leads: 57.53  conf 0.79  because ensemble says 57.53 ± 7.95
     intuition asks recall for review -> abstains: nothing like this in memory   (belief 0.78 -> 0.78)
  => answers 57.53 from intuition (belief 0.78)  [truth 55.8: correct]  compute 3.8
```

### Escalation: a weak lead hands over to a stronger node

```text
task #344  [10.7, 12.69, 16.79, 21.78, 28.49, 33.04, 35.68, 37.09, ?]  tolerance ±1.1  (hidden family: saturating)
  intuition declines: looked, unlikely to help (p~0.25, sampled 0.36)
  recall    bids p=0.72 (calibrated 0.69), needs 0.0 more compute
  inducer   bids p=0.87 (calibrated 0.91), needs 0.0 more compute
  -> inducer leads: 40.86  conf 0.50  because ~x[n] = x[n-1] + 3.77  (best approximate law, sd 1.99)
     inducer asks recall for review -> abstains: nothing like this in memory   (belief 0.49 -> 0.49)
  -> recall leads: 37.17  conf 0.69  because recalls mid match -> 37.17
     recall skips review (not worth the compute at this confidence)
  => answers 37.17 from recall (belief 0.59)  [truth 37.58: correct]  compute 3.2
```

### A reviewer overrules the lead with a better answer

```text
task #1038  [10.33, 12.67, 22.52, 38.63, 55.72, 68.02, 72.79, 76.92, ?]  tolerance ±2.9  (hidden family: saturating)
  recall    declines: looked, unlikely to help (p~0.45, sampled 0.36)
  intuition bids p=0.76 (calibrated 0.72), needs 0.9 more compute
  inducer   bids p=1.00 (calibrated 0.95), needs 0.0 more compute
  -> inducer leads: 93.85  conf 0.74  because ~x[n] = 2.77*x[n-1] - 3.27*x[n-2] + 1.75*x[n-3]  (best approximate law, sd 2.06)
     inducer asks intuition for review -> REJECTS: independently got 78.10, 5.4x tolerance away   (belief 0.65 -> 0.14)
     intuition counter-proposes 78.1 (conf 0.74)
  => answers 78.1 from intuition (belief 0.79)  [truth 78.38: correct]  compute 4.1
```

### Peer review raises the council's confidence

```text
task #414  [6.175, 8.642, 14.35, 22.29, 26.83, 28.54, 29.1, 28.98, ?]  tolerance ±0.95  (hidden family: saturating)
  recall    declines: looked, unlikely to help (p~0.60, sampled 0.26)
  intuition bids p=0.79 (calibrated 0.65), needs 0.9 more compute
  inducer   bids p=0.74 (calibrated 0.65), needs 0.0 more compute
  -> inducer leads: 28.35  conf 0.60  because ~x[n] = 1.18*x[n-1] - 0.474*x[n-2] + 7.91  (best approximate law, sd 1.43)
     inducer asks critic for review -> endorses: consistent with bounded-step   (belief 0.50 -> 0.56)
     inducer asks recall for review -> abstains: nothing like this in memory   (belief 0.56 -> 0.56)
  => answers 28.35 from inducer (belief 0.56)  [truth 29.01: correct]  compute 3.6
```

### Honest abstention instead of a wrong answer

```text
task #540  [2.079, -6.123, -11.17, -11.71, -10.12, -4.323, 2.037, 10.69, ?]  tolerance ±3.7  (hidden family: wave)
  recall    declines: looked, unlikely to help (p~0.43, sampled 0.47)
  intuition bids p=0.56 (calibrated 0.74), needs 0.9 more compute
  inducer   bids p=0.87 (calibrated 0.57), needs 0.0 more compute
  -> inducer leads: 14.09  conf 0.46  because ~x[n] = 0.98*x[n-1] + 0.196*x[n-2] - 0.744*x[n-3]  (best approximate law, sd 4.68)
     inducer asks critic for review -> endorses: consistent with bounded-step   (belief 0.50 -> 0.48)  [this reviewer endorses nearly everything here, so a yes means little]
     inducer asks recall for review -> abstains: nothing like this in memory   (belief 0.48 -> 0.48)
  -> intuition leads: 19.73  conf 0.25  because ensemble says 19.73 ± 5.97
     intuition asks critic for review -> endorses: consistent with bounded-step   (belief 0.48 -> 0.48)
     intuition asks recall for review -> abstains: nothing like this in memory   (belief 0.48 -> 0.48)
  => council abstains (no answer it believes enough)   [truth 17.83]
```

### Inducer quarantined: the others cover what they can

```text
task #1287  [15, 16, 17, 18, 19, 20, 21, 22, ?]  tolerance ±0.5  (hidden family: arithmetic)
  recall    bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  intuition bids p=0.96 (calibrated 0.85), needs 0.9 more compute
  -> recall leads: 23  conf 0.99  because recalls exact match -> 23.00
     recall skips review (not worth the compute at this confidence)
  => answers 23 from recall (belief 0.99)  [truth 23: correct]  compute 1.1
     (unlabeled task: answer certified as teaching signal for the others)
```

