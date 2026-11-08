# Manual spot-check: top 10 promos

Each of the top 10 promos from the committed run was read line by line against the screenplay (`python -m hookline inspect --top 10`) and checked against the brief:

1. **Hook:** does something stop the scroll within the first 3 seconds?
2. **Cliffhanger:** does it cut on an unresolved moment?
3. **Standalone:** does it make sense to a stranger?
4. **Spoiler:** does it give away a late twist?

The run used `gemini-3.5-flash-lite` as the generator and `gemini-3.1-flash-lite` as the judge.

| # | Promo | Ep | Len | Hook ≤3s | Cliffhanger | Standalone | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | The Sadistic Ultimatum | 12 | 43s | Yes: "I want to see you crawl, sister." at 0.0s | Yes: she agrees to crawl into the briars to save her husband from the gallows | Yes: the stakes are spelled out in the clip | Pass |
| 2 | Crawling Through Razor Thorns | 13 | 38s | Yes: "Stop!" and her scream | **No.** It ends as she finds the ring, which resolves the scene | Partly: why she is crawling is never shown | Weak |
| 3 | Gerald Abandons Juliana at Altar | 1 | 55s | Yes: "You should turn around, Juliana." at 0.3s | Yes: "You swore you loved me!" | Yes | Pass |
| 4 | Today He Comes Home | 39 | 35s | Yes: "They buried Alexander Ashwin three years ago." | Yes: "I am bringing my wife home." | Yes | Pass, but **late-series** (see failure 3) |
| 5 | The Scarred Stranger's Proposal | 3 | 48s | Yes: "Take your hands off her." | Yes: "Lady Juliana... accept my hand." | Yes | Pass (condensed by code into 2 segments) |
| 6 | Defending the Ruined Garden | 15 | 50s | Yes: "Stop! What are you doing?!" at 1.0s | Yes: "You want to fight us, veteran?" | Yes | Pass |
| 7 | Unmasked as Lady Juliana Ashcroft | 28 | 40s | Yes: identity reveal line at 0.0s | Yes: threat of the gallows | Yes | Pass |
| 8 | Planted Evidence Frame-Up | 11 | 21s | Yes: "That is his coat!" | Yes: evidence pulled from his coat | **Partly:** who is framed, and why, is unclear cold | Weak |
| 9 | Trapped in the Inferno | 18 | 25s | Yes: a scream inside a burning room | **No.** It ends on "I've got you.", a completed rescue | Yes | Fail |
| 10 | Humiliated by the Noblewoman | 24 | 59s | Yes: riding-crop strike at 1.5s | Mild: a vow of return | Yes | Pass (long) |

**Result: 7 pass, 2 weak, 1 fail.** Every hook landed in the first 3 seconds; the code enforces that. The misses are all about the *ending* or about *context*, which the model judges and code cannot check.

## Failure modes found

1. **"Cliffhangers" that resolve.** The generator sometimes labels the end of a rescue or a search as the cliffhanger (#2, #9). These are dramatic peaks, but the tension has already been released.
2. **The judge is lenient.** The lite judge gave 4–5 on almost every dimension to all ten clips, including the two with resolved endings. Its scores rank strong clips above weak ones overall (see the baseline comparison in `results.md`), but they do not separate a 5 from a 4 reliably.
   - *Fix:* use a stronger judge model (one flag: `--judge-model`), or replace absolute 1–5 scores with pairwise "which would you post?" comparisons.
3. **Spoiler policy is a judgement call.** #4 is from Episode 39 and shows the hero returning as the presumed-dead Duke. The series bible marked "Alexander is the true Duke" as not ad-safe, but the keyword check missed this paraphrase, and the show's own title already says "He was a Duke".
   - *Fix:* an editor sets ad-safe reveals per show; semantic matching instead of keywords.
4. **Context-dependent clips.** #8 needs the previous episode to make sense. The judge rated it 4/5 standalone, which a human would not.
5. **Text-only blind spots.** Clip #6 opens on a camera move and only has its line at 1.0s. Whether the first second actually grabs attention depends on the footage, which the tool never sees.

## What would make this better

- A stronger or different-family judge model, and pairwise ranking.
- Feed editor approvals and rejections back into the ranking weights and prompts.
- A rule that flags endings where the last spoken line resolves the tension, such as "I've got you." or "You're safe.", for editor review.
