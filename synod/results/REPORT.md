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
| synod | **+0.675** ± 0.036 | 81% | 8% | 11% | 2.43 | +0.68 (5% wrong) | +0.40 (18% wrong) |
| neural-only | +0.085 ± 0.038 | 20% | 9% | 71% | 1.50 | +0.13 (5% wrong) | +0.09 (12% wrong) |
| symbolic-only | +0.631 ± 0.023 | 73% | 6% | 20% | 1.84 | +0.71 (4% wrong) | -0.08 (17% wrong) |
| hand-written gate | +0.522 ± 0.013 | 63% | 9% | 28% | 1.08 | +0.50 (5% wrong) | +0.01 (23% wrong) |
| synod w/o review | +0.661 ± 0.041 | 81% | 10% | 10% | 2.45 | +0.65 (12% wrong) | +0.35 (22% wrong) |
| synod w/o trust | +0.664 ± 0.035 | 80% | 9% | 12% | 2.46 | +0.61 (10% wrong) | +0.35 (21% wrong) |
| synod w/o exchange | +0.646 ± 0.036 | 78% | 9% | 13% | 2.47 | +0.57 (12% wrong) | +0.26 (23% wrong) |
| synod w/o self-healing | +0.584 ± 0.013 | 76% | 12% | 12% | 2.78 | +0.54 (14% wrong) | -0.30 (59% wrong) |

Utility per 100-task window (seed mean):

| window | synod | symbolic-only | hand-written gate | synod w/o self-healing |
|---|---|---|---|---|
| 0-99 | +0.45 | +0.56 | +0.42 | +0.45 |
| 100-199 | +0.62 | +0.65 | +0.49 | +0.61 |
| 200-299 | +0.62 | +0.68 | +0.49 | +0.60 |
| 300-399 | +0.68 | +0.68 | +0.46 | +0.65 |
| 400-499 | +0.72 | +0.74 | +0.56 | +0.72 |
| 500-599 | +0.71 | +0.73 | +0.49 | +0.63 |
| 600-699 | +0.71 | +0.74 | +0.59 | +0.67 |
| 700-799 | +0.67 | +0.65 | +0.53 | +0.65 |
| 800-899 | +0.76 | +0.71 | +0.60 | +0.74 |
| 900-999 | +0.78 | +0.77 | +0.62 | +0.75 |
| 1000-1099 | +0.77 | +0.75 | +0.56 | +0.72 |
| 1100-1199 | +0.79 | +0.73 | +0.70 | +0.77 |
| 1200-1299 | +0.57 | +0.31 | +0.33 | +0.19 |
| 1300-1399 | +0.53 | +0.00 | +0.14 | -0.09 |
| 1400-1499 | +0.60 | +0.60 | +0.63 | +0.51 |
| 1500-1599 | +0.82 | +0.80 | +0.74 | +0.77 |

## Who ended up doing what (seed 0) - emergent, never programmed

Share of delivered answers per hidden family. Nodes never see the family.

| family | t 300-549 (warmed up) | t 1450-1599 (after faults and shift) |
|---|---|---|
| affine | recall 94%, inducer 6% | recall 100% |
| arithmetic | recall 96%, inducer 4% | recall 100% |
| fibonacci | inducer 96%, recall 4% | inducer 80%, recall 20% |
| geometric | recall 100% | recall 100% |
| interleaved | - | inducer 93%, recall 7% |
| noisy_trend | inducer 61%, recall 24%, abstain 12%, intuition 2% | inducer 54%, recall 29%, intuition 17% |
| quadratic | inducer 81%, recall 15%, abstain 4% | inducer 77%, recall 23% |
| saturating | recall 49%, abstain 36%, inducer 13%, intuition 3% | recall 52%, intuition 48% |
| wave | inducer 51%, abstain 33%, recall 14%, intuition 2% | intuition 58%, inducer 35%, recall 8% |

## What the nodes decided on their own (seed 0)

- t=550 **world**: neural memory index corrupted (confidently wrong)
- t=552 **intuition**: retracted 2 lessons learned from recall
- t=552 **recall**: drift alarm -> self-test failed (accuracy down 60%): repaired itself, now on probation
- t=602 **recall**: probation complete: back in service
- t=1000 **world**: new family appears: interleaved sequences
- t=1250 **world**: bug in symbolic evaluator (+1 offset)
- t=1273 **inducer**: surprised by a miss at 99% confidence -> self-test failed (accuracy down 65%): cannot self-repair, quarantined itself
- t=1273 **intuition**: retracted 17 lessons learned from inducer
- t=1273 **recall**: retracted 36 lessons learned from inducer
- t=1400 **world**: operator ships a hotfix
- t=1422 **inducer**: self-test passed (accuracy drop 0%): leaving quarantine on probation
- t=1451 **inducer**: probation complete: back in service

Self-checks that came back clean (false alarms, cost only maintenance compute): intuition 2, recall 2, inducer 3.

## What the symbolic side learned (seed 0)

Concepts the inducer invented (laws confirmed often enough to be checked first, almost for free):

- `x[n] = x[n-1] + x[n-2]` (confirmed 79x)
- `x[n] = 2*x[n-1]` (confirmed 7x)
- `x[n] = -2*x[n-1]` (confirmed 6x)
- `x[n] = 3*x[n-1] + 1` (confirmed 5x)
- `x[n] = 3*x[n-1]` (confirmed 5x)
- `x[n] = x[n-2] + 9` (confirmed 4x)
- `x[n] = x[n-2] + 6` (confirmed 4x)
- `x[n] = x[n-2] - 1` (confirmed 4x)

Situations where it learned exact laws never turn up, so it stopped hunting for them and switched to cheap approximate laws:

- loose / real / smooth / steady
- loose / real / rough / steady
- loose / real / smooth / decaying
- loose / real / smooth / explosive
- loose / real / rough / decaying

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
| critic | endorsed | lead right | 55 |
| critic | endorsed | lead wrong | 25 |
| critic | rejected | lead right | 1 |
| inducer | abstained | lead right | 6 |
| inducer | abstained | lead wrong | 4 |
| inducer | endorsed | lead right | 8 |
| inducer | rejected | lead wrong | 4 |
| intuition | abstained | lead right | 1 |
| intuition | abstained | lead wrong | 1 |
| intuition | endorsed | lead right | 12 |
| intuition | endorsed | lead wrong | 6 |
| intuition | rejected | lead right | 8 |
| intuition | rejected | lead wrong | 5 |
| recall | abstained | lead right | 104 |
| recall | abstained | lead wrong | 34 |
| recall | endorsed | lead right | 39 |
| recall | rejected | lead right | 3 |
| recall | rejected | lead wrong | 1 |

## Sample deliberations (seed 0, auto-picked)

### A symbolic law, no review needed

```text
task #305  [21, 49, 70, 119, 189, 308, 497, 805, ?]  tolerance ±0.5  (hidden family: fibonacci)
  recall    declines: looked, unlikely to help (p~0.24, sampled 0.08)
  intuition declines: rarely useful here (p_useful~0.01)
  inducer   bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  -> inducer leads: 1302  conf 0.99  because x[n] = x[n-1] + x[n-2]  (concept recurrence-2[1.0, 1.0])
     inducer skips review (not worth the compute at this confidence)
  => delivers 1302 from inducer (belief 0.95)  [truth 1302: correct]  compute 0.6
     (unlabeled task: answer certified as teaching signal for the others)
```

### Memory covers a known shape; others don't bother looking

```text
task #301  [0, 4, 12, 28, 60, 124, 252, 508, ?]  tolerance ±0.5  (hidden family: affine)
  intuition declines: rarely useful here (p_useful~0.00)
  inducer   declines: already covered by recall (belief 0.99)
  recall    bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  -> recall leads: 1020  conf 0.99  because recalls exact match -> 1020.00
     recall skips review (not worth the compute at this confidence)
  => delivers 1020 from recall (belief 0.99)  [truth 1020: correct]  compute 0.5
     (unlabeled task: answer certified as teaching signal for the others)
```

### Neural intuition handles a noisy nonlinear series

```text
task #565  [-8.30, -7.73, -3.95, 1.60, 9.13, 15.70, 20.07, 21.61, ?]  tolerance ±3  (hidden family: wave)
  inducer   declines: looked, unlikely to help (p~0.46, sampled 0.40)
  intuition bids p=0.93 (calibrated 0.81), needs 0.9 more compute
  -> intuition leads: 23.04  conf 0.76  because ensemble says 23.04 ± 3.39
     intuition skips review (not worth the compute at this confidence)
  => delivers 23.04 from intuition (belief 0.80)  [truth 20.18: correct]  compute 3.2
```

### Escalation: a weak lead hands over to a stronger node

```text
task #399  [18.85, 15.33, 3.81, -9.24, -17.49, -14.33, -3.71, 8.97, ?]  tolerance ±3.7  (hidden family: wave)
  system pressure 0.08 -> everyone is more cautious
  intuition declines: looked, unlikely to help (p~0.35, sampled 0.39)
  recall    bids p=0.81 (calibrated 0.51), needs 0.0 more compute
  inducer   bids p=0.69 (calibrated 0.82), needs 0.0 more compute
  -> recall leads: 22.68  conf 0.51  because recalls far match -> 22.68
     recall skips review (not worth the compute at this confidence)
  -> inducer leads: 15.81  conf 0.87  because ~x[n] = 0.707*x[n-1] - 0.00955*x[n-2] - 0.658*x[n-3]  (best approximate law, sd 0.97)
     inducer asks recall for review -> abstains: nothing like this in memory   (belief 0.75 -> 0.75)
  => delivers 15.81 from inducer (belief 0.75)  [truth 18.03: correct]  compute 3.2
```

### A reviewer overrules the lead with a better answer

```text
task #633  [11, 14, 25, 39, 64, 103, 167, 270, ?]  tolerance ±0.5  (hidden family: fibonacci)
  intuition declines: rarely useful here (p_useful~0.00)
  recall    bids p=0.95 (calibrated 0.58), needs 0.0 more compute
  inducer   bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  -> recall leads: 436.50  conf 0.58  because recalls near match -> 436.50
     recall asks inducer for review -> REJECTS: law x[n] = x[n-1] + x[n-2]  (concept recurrence-2[1.0, 1.0]) gives 437   (belief 0.66 -> 0.20)
     inducer counter-proposes 437 (conf 0.99)
  => delivers 437 from inducer (belief 0.59)  [truth 437: correct]  compute 0.6
```

### Peer review raises the council's confidence

```text
task #310  [-4.80, -6.01, -3.43, -4.29, -5.02, -4.17, -5.56, -5.60, ?]  tolerance ±1.1  (hidden family: noisy_trend)
  intuition declines: rarely useful here (p_useful~0.02)
  recall    bids p=0.79 (calibrated 0.48), needs 0.0 more compute
  inducer   bids p=0.71 (calibrated 0.72), needs 6.9 more compute
  -> inducer leads: -4.86  conf 0.58  because ~x[n] = -4.86  (best approximate law, sd 0.92)
     inducer asks intuition for review -> endorses: independently got -5.10   (belief 0.50 -> 0.61)
     inducer asks recall for review -> abstains: nothing like this in memory   (belief 0.61 -> 0.61)
  => delivers -4.86 from inducer (belief 0.61)  [truth -5.53: correct]  compute 10.7
```

### Honest abstention instead of a wrong answer

```text
task #466  [-7.26, -11.06, -8.65, -8.36, -8.22, -7.40, -11.56, -12.79, ?]  tolerance ±2.9  (hidden family: noisy_trend)
  system pressure 0.31 -> everyone is more cautious
  inducer   declines: looked, unlikely to help (p~0.41, sampled 0.14)
  recall    bids p=0.95 (calibrated 0.87), needs 0.0 more compute
  intuition bids p=0.80 (calibrated 0.63), needs 0.9 more compute
  -> intuition leads: -16.87  conf 0.55  because ensemble says -16.87 ± 2.42
     intuition asks critic for review -> endorses: consistent with bounded-step   (belief 0.56 -> 0.48)  [this reviewer endorses nearly everything here, so a yes means little]
     intuition asks recall for review -> abstains: nothing like this in memory   (belief 0.48 -> 0.48)
  -> recall leads: -13.82  conf 0.87  because recalls far match -> -13.82
     recall asks intuition for review -> REJECTS: independently got -16.87, 1.1x tolerance away   (belief 0.66 -> 0.57)
     intuition counter-proposes -16.87 (conf 0.55)
     recall asks critic for review -> endorses: consistent with bounded-step   (belief 0.57 -> 0.49)  [this reviewer endorses nearly everything here, so a yes means little]
  => council abstains (no answer it believes enough)   [truth -10.54]
```

### Inducer quarantined: the others cover what they can

```text
task #1287  [15, 16, 17, 18, 19, 20, 21, 22, ?]  tolerance ±0.5  (hidden family: arithmetic)
  intuition declines: looked, unlikely to help (p~0.75, sampled 0.43)
  recall    bids p=1.00 (calibrated 1.00), needs 0.0 more compute
  -> recall leads: 23  conf 0.99  because recalls exact match -> 23.00
     recall skips review (not worth the compute at this confidence)
  => delivers 23 from recall (belief 0.99)  [truth 23: correct]  compute 1.1
     (unlabeled task: answer certified as teaching signal for the others)
```

