# Evaluation results

## Blind cold-viewer judge scores (1-5)

| | n | hook | cliff | standalone | emotion | weighted |
|---|---|---|---|---|---|---|
| Baseline: last 45 s of every episode | 48 | 3.75 | 4.08 | 3.79 | 4.25 | 3.94 |
| Baseline: best 15 by judge score | 15 | 4.73 | 4.6 | 4.4 | 4.93 | 4.66 |
| Hookline: all promos | 56 | 3.8 | 3.7 | 3.66 | 4.09 | 3.8 |
| Hookline: best 15 by judge score | 15 | 4.87 | 4.53 | 4.07 | 4.93 | 4.6 |
| Hookline: top 15 in posting order | 15 | 4.73 | 4.33 | 4.07 | 4.93 | 4.51 |

## Objective hook check

A spoken line starts within the first 3 seconds: baseline **79%**, Hookline **98%**.

## Stability

A second pass with `gemini-3.1-flash-lite (temperature 0.4)` re-mined 25 episodes and re-found **60%** of the top-10 continuous promos from those episodes (time overlap > 50%).

## Constraint checks

Proposed 71 · valid 57 · auto-repaired 41 · rejected 14 · duplicates removed 1 · final 56 · unjudged 0
