# Hookline — AI promo finder for microdrama screenplays (design)

Date: 2026-11-08 · Author: Lavanya Nair (GitHub `aynaval`) · Built with Claude Code

## 1. Intent

Kuku Problem 1, "Find the Promos". Today an editor watches every episode and picks promo moments by hand, one show at a time, and Kuku releases new shows every week. Hookline reads a show's timestamped screenplays and returns a **ranked list of ready-to-cut promos**. For each one it gives:

- the episode and the exact start and end timestamps of every segment, in order
- the hook (what stops the scroll in the first 3 seconds)
- the cliffhanger (the unresolved moment it cuts on)
- one line on why it works
- its rank, and why it should be posted in that position

The editor's job changes from watching 50 episodes to reviewing about 20 suggestions.

**Why Problem 1.** Kuku supplied real data for it, the output can be checked objectively (timestamps), it maps directly to a weekly cost Kuku pays, and it can be hosted for free as a small Python app. Problems 2 and 3 carry more risk for the time we have.

## 2. Goals / non-goals / anti-goals

**Goals**
1. Run end to end on the full 50-episode input pack and produce raw outputs (JSON, CSV and a readable Markdown report).
2. Produce both **continuous** promos (one 20–60 s stretch) and **stitched** promos (2–3 moments joined, from one episode or several).
3. Rank the promos and explain the posting order.
4. Swap models with one setting. Any OpenAI-compatible endpoint works: Gemini (default), OpenAI, Anthropic, Groq, OpenRouter, Ollama, or whatever endpoint Kuku provides in the interview.
5. Re-runnable on a new show, both from the CLI and from the hosted app (upload `.txt` files or a `.zip`).
6. Quality checking backed by real runs: automatic constraint checks, a baseline comparison, a stability check, and an honest list of failure cases.
7. A free, public deployment on Streamlit Community Cloud, a public GitHub repo, and a 2-page PDF solution doc.

**Non-goals**
- Video editing, music, captions or text overlays (out of scope per the brief).
- Working from video or audio. We only have screenplays.
- Predicting real click-through or ad performance.

**Anti-goals (failure even if it "works")**
- **Hallucinated timestamps.** Every timestamp must come from a real line of the script. The model points at line IDs, and code converts those IDs to timestamps.
- **Cutting mid-line.** No promo may start or end in the middle of a line of dialogue.
- **Publishing Kuku's confidential screenplays.** The input pack never goes into the public repo or the public app. Committed outputs contain only timestamps plus the short hook and cliffhanger quotes the deliverable requires.
- **Overclaiming.** The doc says plainly where the tool picks badly.

## 3. Constraints

- Free tiers only. Gemini API free tier, Streamlit Community Cloud, public GitHub.
- The input pack must not be published (see the brief's confidentiality note).
- Git identity: commits as `aynaval <lavanya.nair.bce22@itbhu.ac.in>`, set **in the repo's own config only**. The global git config and the existing `gh` login (`satyam-effano`) stay untouched. `gh` for `aynaval` uses a separate config folder (`GH_CONFIG_DIR=/Users/abc/Desktop/KukuFM/.gh-aynaval`, outside the repo), and the repo's credential helper points at it.
- Local Python is 3.9.6. We'll use an isolated Python 3.12 (via `uv`) in the project's `.venv`, and pin 3.12 on Streamlit Cloud.
- Solution doc: a PDF of at most 2 pages.
- A short time budget, so we avoid gold-plating.

## 4. Input format (observed)

Each episode file has `EPISODE NUMBER`, `EPISODE LOGLINE`, `CONTINUITY NOTES`, then `SCENE NN` blocks (heading, scene start and end). Each scene contains labelled lines:

```
**CAMERA:** / **ACTION:** / **SOUND FX:** / **<SPEAKER> (<emotion>):**
Start: (MM:SS.ss) | End: (MM:SS.ss)
<text>
```

The pack has 50 episodes and 3,727 timestamped lines. Episodes run about 2–3.5 minutes, and timestamps are relative to the episode. Speaker names have aliases (`LADY JULIANA` = `JULIANA`; `LADY IN GOLD GOWN` = `CLARISSA`), and camera, action and dialogue lines overlap in time.

## 5. How it works

```
screenplays ─► [1 Parse: code] ─► beats + episode meta
                                   │
             [2 Series bible: LLM, 1 call]  characters, aliases, arcs, big reveals (spoilers)
                                   │
             [3 Mine each episode: LLM, 1 call/episode]  continuous candidates + hook/cliff "moments"
                                   │
             [4 Stitch: LLM, 1 call on moment catalogue]  2–3 segment promos (cross-episode allowed)
                                   │
             [5 Validate & snap: code]  beat IDs → timestamps, 20–60 s, hook ≤3 s, no mid-line cuts, dedupe
                                   │
             [6 Cold-viewer judge: LLM, 1 call/candidate batch]  scores with NO series context
                                   │
             [7 Rank: code]  weighted score + funnel/spoiler logic + diversity
                                   │
             outputs/: promos.json · promos.csv · report.md · run_meta.json · raw/ (every LLM response)
```

**1 Parse (code, deterministic).** A regex parser turns each episode into beats: `{id: "E07-B031", ep, scene, kind: CAMERA|ACTION|DIALOGUE|SFX, speaker, emotion, start, end, text}`. It reports parse warnings rather than crashing, which matters because new shows may differ slightly. Unit tests cover it.

**2 Series bible (LLM).** Input: all episode loglines and continuity notes. Output JSON: main characters with their aliases, the core premise in one line, major arcs, and a list of **spoiler reveals** with the episode where each is revealed (for example, the husband secretly being a Duke). Later prompts use it so the model understands who is who.

**3 Mine each episode (LLM, run in parallel with a rate limiter).** Input: the bible plus the episode's beats in a compact form (`[B031 00:39.1–00:41.2] DIALOGUE CLARISSA (Gloating): "Because he is marrying me."`). Camera and action lines stay in, because slaps and reveals are often visual. Output JSON:
- 2–4 **continuous candidates**: `start_beat`, `end_beat`, `hook_beat`, `cliff_beat`, hook and cliffhanger text, why it works, and the context a cold viewer would need
- **moments**: the episode's strongest standalone hook beats and cliffhanger beats, with one-line context, used by stage 4

The model must refer to **beat IDs only, never timestamps**.

**4 Stitch (LLM).** Input: the bible plus the catalogue of moments from every episode (compact, around 10–20K tokens). Output: 6–10 stitched promos with 2–3 segments each. A common pattern is the cold open: a shocking moment first, then the context, then a cliffhanger. Segments may come from different episodes, and their order is the play order.

**5 Validate & snap (code).** This is where correctness is enforced:
- Beat IDs are resolved to timestamps. Unknown IDs are rejected and logged.
- Each segment runs from its first beat's start to its last beat's end, so no line is cut in half. Overlapping lines (camera vs dialogue) are expanded so the segment doesn't end in the middle of a spoken line.
- Total duration must be 20–60 s. If it's close, the code adjusts the boundary toward the nearest line edge. If it can't be fixed, the candidate is dropped and the reason is logged.
- The hook must start within 3 s of the promo's start.
- The cliffhanger line must be the last line of the last segment, or end within 1 s of it.
- Near-duplicates (more than 50% overlap with a higher-scored candidate) are removed.

Rejections and repairs go into `run_meta.json`; they're a quality metric.

**6 Cold-viewer judge (LLM).** Each surviving candidate is shown **only the text of its own segments**: no bible, no other episodes. This simulates a stranger scrolling. The judge scores each from 1 to 5 on:
- hook strength (the first 3 s)
- cliffhanger strength
- standalone clarity (and states in one line what a cold viewer understands)
- emotional and trope pull (betrayal, humiliation, revenge, hidden identity, slaps, reveals)

It also gives a **spoiler risk** from 0 to 2, checked against the bible's reveal list by code. Keeping the judge's context separate from the generator's reduces self-agreement bias.

**7 Rank (code).** `score = weighted judge scores + duration sweet spot (30–45 s) − spoiler penalty`. The **posting order** isn't a plain sort:
1. Post early-episode, low-spoiler, high-hook promos first. A viewer who clicks lands on Episode 1, so a promo whose payoff is a few episodes away converts better.
2. Then take diversity into account: we don't post three promos from the same scene back to back.

Each promo gets a one-line "why post at #N".

**Outputs.**
- `promos.json` (the full structure)
- `promos.csv` (one row per segment, for editors and spreadsheets)
- `report.md` (the ranked, readable list)
- `run_meta.json` (model, prompt version, token counts, cost estimate, timings, validation stats)
- `raw/` (every unedited LLM response, which the brief requires)

## 6. Model layer (swappable)

`llm.py` is a thin wrapper over the `openai` Python SDK. Every provider in scope exposes an OpenAI-compatible API, so it uses `base_url` presets: `gemini` (default), `openai`, `anthropic`, `groq`, `openrouter`, `ollama`, `custom`. It's configured with `HOOKLINE_PROVIDER`, `HOOKLINE_MODEL`, `HOOKLINE_API_KEY` and an optional `HOOKLINE_BASE_URL`, or from the app's sidebar. It does three things:
- asks for JSON output, then parses and validates it with Pydantic, retrying once with the error on bad JSON
- retries with backoff on rate limits
- counts tokens

The default model is the best Gemini Flash model available on the free tier, checked by listing models with the key at build time (expected `gemini-2.5-flash`, or a newer Flash). Prompts live in `prompts/*.md`, versioned, so a reviewer can read them.

## 7. Interfaces

- **CLI** (used for the interview re-run): `python -m hookline run --input <dir|zip> --out outputs/<show> [--provider gemini --model ...]`.
- **Streamlit app** (`app.py`), with three tabs:
  - **Results**: the ranked promo cards from the committed 50-episode run (rank, total duration, segment table, hook, cliffhanger, why, scores, why-post-at-#N). An editor can tick approve or reject on each card and export the approved ones as CSV. This is the human-in-the-loop step.
  - **Run on a new show**: upload `.txt` files or a `.zip`, pick a provider, model and key (defaulting to our Gemini key in Streamlit secrets), watch a progress bar, then view and download JSON, CSV or MD. Script excerpts appear only for uploaded files in that session, never from committed data.
  - **Quality**: validation stats, baseline comparison, stability, known failure cases.

## 8. Quality checking

1. **Constraint pass rate (automatic).** The share of LLM candidates that pass validation without repair, are repaired, or are rejected. Every final promo satisfies 20–60 s, hook ≤ 3 s, line-aligned cuts and real timestamps by construction.
2. **Baseline comparison.** A naive rule-based baseline takes the last ~45 s of each episode (episodes end on cliffhangers, so it's a fair baseline). The same cold-viewer judge scores the baseline and Hookline's top picks, and we report the difference in hook and standalone scores. This shows what the LLM adds beyond "cut the ending".
3. **Stability.** Run mining twice, at a different temperature or with a second model if quota allows, and report the overlap of the top 10 promos (time-overlap ≥ 50%).
4. **Human spot-check.** Lavanya, with Claude's help, reviews the top 10 against the actual script lines using a short checklist (does the hook land in 3 s? does it cut on an open question? does it make sense cold? is there a spoiler?). Pass/fail and notes go in `eval/spot_check.md`.
5. **Honest failure list**, documented as found. Expected ones:
   - only text is available, so the tool can't judge acting or visual punch
   - script timestamps may drift from the final cut
   - the generator and judge are the same model family
   - alias confusion
   - stitched promos can feel disjointed
   - spoilers

## 9. Scale & cost (to be filled from the real run)

The per-show token counts from `run_meta.json` are multiplied by paid Flash pricing to give a cost per show, which we expect to be cents. We'll also report the time per show.

At scale:
- each show runs as one batch job when its scripts land
- the editor reviews the top ~20 instead of watching every episode
- approvals and rejections are logged, to later tune the ranking weights and the prompts

## 10. Repo layout

```
hookline/
  hookline/  parse.py  llm.py  pipeline.py  validate.py  rank.py  baseline.py  schemas.py  cli.py  __main__.py
  prompts/   bible.md  mine_episode.md  stitch.md  judge.md
  app.py  requirements.txt  .python-version  .streamlit/config.toml
  outputs/i-married-a-broken-soldier/   (raw outputs from the full pack, committed)
  eval/      baseline + stability + spot_check results
  docs/      solution.md → solution.pdf (2 pages), superpowers specs/plans
  tests/     parser, validator, ranker
  data/      (gitignored, local copy of the input pack)
```

## 11. Delivery stages

1. **Repo and identity.** Create the repo with a repo-local git identity and an isolated `gh` login for `aynaval`, gitignore the input pack, and create the public GitHub repo.
2. **Parser and tests.**
3. **LLM layer.** Confirm the Gemini key works and choose the model.
4. **Pipeline stages 2–7.** Do a smoke run on 3 episodes and inspect it.
5. **Full run** on all 50 episodes, then commit the raw outputs.
6. **Evaluation.** Baseline, stability and spot-check.
7. **Streamlit app**, tested locally.
8. **Deploy to Streamlit Cloud.** Sign in with `aynaval` GitHub in the browser and add the Gemini key as a secret.
9. **Solution doc PDF** (2 pages), rendered with headless Chrome, plus a README with run steps.
10. **Walkthrough video script** (optional, for Lavanya to record), plus a submission checklist covering form fields and link-visibility checks.

## 12. Left to the builder

- prompt wording
- exact score weights (start with equal weights and a spoiler penalty)
- the parallelism and rate-limit settings
- the visual styling of the app
- CSV column order

## 13. Needed from Lavanya

- a Gemini API key from aistudio.google.com
- a one-time browser approval for the `aynaval` `gh` login and the Streamlit Cloud sign-in
- reviewing and editing the solution doc in her own words: the brief says the decisions must be hers, and she'll be asked about them in the interview
