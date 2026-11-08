# Hookline

Hookline reads the timestamped screenplays of a vertical microdrama and returns a ranked list of ready-to-cut promos (20 to 60 second clips for TikTok, Reels and Shorts). For every promo it gives the episode and exact start and end timestamps of each segment, the hook, the cliffhanger, one line on why it works, and where it sits in the posting order.

Built for Kuku's AI Generalist assignment, Problem 1 ("Find the Promos").

- Live app: https://hookline-promos.streamlit.app
- Full run on the 50-episode input pack: [`outputs/i-married-a-broken-soldier/report.md`](outputs/i-married-a-broken-soldier/report.md)
- Evaluation: [`eval/`](eval/)
- Solution doc: [`docs/solution.pdf`](docs/solution.pdf)

## What a promo looks like

From the committed run on all 50 episodes of the input pack (56 promos):

```
#1  The Sadistic Ultimatum  (continuous, 43 s)
    1. Ep 12  00:44.00 -> 01:27.21
    Hook:        "I want to see you crawl, sister."
    Cliffhanger: Juliana agrees to dig through frozen thorns to save her husband from the gallows.
    Why post #1: scroll-stopping hook (5/5); 43 s is in the 30-45 s sweet spot

#5  The Scarred Stranger's Proposal  (stitched, 48 s)
    1. Ep 3  01:09.90 -> 01:31.60
    2. Ep 3  01:59.80 -> 02:25.75
    Hook:        "Take your hands off her."
    Cliffhanger: The scarred stranger drops to one knee with a ring.
```

Promos come in two kinds: continuous (one unbroken stretch) and stitched (two or three moments joined, from one episode or several).

## Quick start

Requires Python 3.10+ and a free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).

```bash
git clone https://github.com/ayn-aval/hookline.git
cd hookline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export GEMINI_API_KEY=your-key

# Run on a folder of episode .txt files (or a .zip)
python -m hookline run --input path/to/episodes --out outputs/my-show

# Read the actual script lines of the top promos
python -m hookline inspect --input path/to/episodes --out outputs/my-show --top 5

# Quality checks: blind-judged baseline, stability with a second model, constraint stats
python -m hookline eval --input path/to/episodes --out outputs/my-show --alt-model gemini-3.1-flash-lite --eval-dir eval

# Web app
streamlit run app.py
```

Useful flags:

- `--model` and `--judge-model` set the generator and judge models.
- `--episodes-per-call` sets how many episodes go into one mining call: 1 gives the best quality, the default of 5 keeps a full show inside free-tier request limits.
- `--episodes 1-10` processes a subset.
- `--workers` sets parallel calls.
- `--env-file .env` loads keys from a file.

## Swapping the model

Every supported provider speaks the OpenAI chat-completions protocol, so the model is a setting, not code. Use flags, environment variables or the app sidebar (pick a listed model, or choose "Other" to type any model ID the provider serves; a misspelled name fails on the first call with a clear message).

| Provider | `--provider` | Key variable | Default model |
|---|---|---|---|
| Google Gemini (default) | `gemini` | `GEMINI_API_KEY` | `gemini-3.5-flash-lite`, judge `gemini-3.1-flash-lite` |
| OpenAI | `openai` | `OPENAI_API_KEY` | `gpt-5-mini` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` |
| Groq | `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | `openrouter/auto` |
| Ollama (local) | `ollama` | none | `qwen3:8b` |
| Any other endpoint | `custom` + `--base-url` | `HOOKLINE_API_KEY` | set `--model` |

```bash
python -m hookline run --input episodes/ --out outputs/x --provider custom \
  --base-url https://models.example.com/v1 --model their-best-model
```

Environment equivalents: `HOOKLINE_PROVIDER`, `HOOKLINE_MODEL`, `HOOKLINE_BASE_URL`, `HOOKLINE_API_KEY`.

The judge defaults to a different model from the generator, so a model never grades its own picks. The committed run used `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` because Gemini's free tier allows about 20 requests per model per day. A full 50-episode show takes 15 calls.

## How it works

```
screenplays -> 1 Parse (code) -> 2 Series bible (LLM) -> 3 Mine each episode (LLM)
            -> 4 Stitch across episodes (LLM) -> 5 Validate and snap (code)
            -> 6 Cold-viewer judge (LLM) -> 7 Rank (code) -> editor approves (human)
```

1. **Parse (code).** Every camera note, action, line of dialogue and sound cue becomes a *beat* with a stable ID such as `E07-B031` and its real timestamps.
2. **Series bible (1 LLM call).** Characters and their aliases (the scripts call the same person "LADY IN GOLD GOWN" and "CLARISSA"), the main arcs, and which twists are safe to show in ads.
3. **Mine (1 call per 5 episodes by default).** Two to four continuous promo windows per episode, plus the episode's standout hook and cliffhanger moments. The model answers with beat IDs only.
4. **Stitch (1 call).** Two or three moments joined into a promo, for example a shocking cold open followed by the setup and a cliffhanger.
5. **Validate (code).** Beat IDs become timestamps. The rules below are enforced here, not trusted to the model. Candidates that cannot be repaired are rejected with a logged reason, and near-duplicates are removed.
6. **Judge (LLM, batches of 20, separate model).** Each clip is scored 1 to 5 on hook, cliffhanger, standalone clarity and emotional pull. The judge sees only the clip's own lines and no series context, which tests "makes sense on its own" instead of assuming it.
7. **Rank (code).** A weighted judge score, a bonus for the 30 to 45 second sweet spot, a spoiler penalty and a preference for early episodes (a new viewer who clicks starts at Episode 1, so a promo from Episode 2 pays off sooner than one from Episode 40). The order also avoids posting two promos from the same episode back to back.

### Rules enforced in code

| Rule | How |
|---|---|
| Timestamps are real | The model can only cite beat IDs. Unknown IDs reject the candidate. |
| 20 to 60 seconds | Total of all segments. An over-long window is condensed to the hook opening plus the run-up to the cliffhanger. A short stitched promo gets a longer run-up. Anything else out of range is rejected. |
| Hook in the first 3 seconds | The start moves onto the hook beat, earlier or later as needed. A promo that is slightly short may open up to 3 s before the hook. |
| Ends on the cliffhanger | The end moves onto the cliffhanger beat (within 1 s), earlier or later as needed. |
| No cut mid-sentence | A cut that lands inside a spoken line is widened to the whole line. |

The thresholds and ranking weights live in [`hookline/rules.py`](hookline/rules.py).

## Outputs

Each run folder contains:

| File | Contents |
|---|---|
| `report.md` | Readable ranked list with segments, hook, cliffhanger, reasons and judge notes |
| `promos.csv` | One row per segment, for editors and spreadsheets |
| `promos.json` | Full structured output, including the series bible and run metadata |
| `run_meta.json` | Model, prompt fingerprint, candidate counts, rejections, token usage, cost estimate, timing |
| `raw/` | Every model reply, unedited, one file per call (including judge batches superseded by later rule changes). Calls are cached, so re-running is free and resumes after failures. |

## Project structure

```
hookline/
  parse.py         screenplay text -> beats with IDs and timestamps
  schemas.py       Beat, Episode, Candidate, Segment, Promo
  llm/             provider presets, the JSONModel protocol, cached and retrying OpenAI-compatible client
  prompts/         versioned prompt templates (Markdown)
  stages/          bible, mine, stitch, judge, spoilers: the LLM-backed steps
  render.py        text renderings of beats and clips for prompts and the UI
  validate.py      promo rules, snapping, de-duplication
  rank.py          posting order
  rules.py         thresholds and weights
  batching.py      splitting work into LLM-call-sized batches
  pipeline.py      orchestration of one run
  report.py        writing and reading run outputs
  baseline.py      naive "last 45 seconds" baseline
  evaluate.py      baseline, stability and constraint checks
  cli.py           run / eval / inspect
webapp/            Streamlit views and components
app.py             Streamlit entry point
outputs/           committed run on the input pack
eval/              evaluation results and manual spot-check
docs/              solution doc, design spec and plan
tests/             unit and end-to-end tests (no network)
```

## Results and evaluation

On the 50-episode pack, the model proposed 71 candidates. 41 were auto-repaired and 14 rejected, leaving 56 promos. The run took about 2 minutes and 15 calls, roughly $0.16 at paid prices.

| Check | Result |
|---|---|
| Spoken line within the first 3 s | Hookline 98%, baseline (last 45 s of each episode) 79% |
| Blind judge, best 15 (weighted 1-5) | Hookline 4.60, baseline 4.66: the judge cannot separate them |
| Stability (second model, episodes 1-25) | 60% of the top-10 promos re-found |
| Manual top-10 spot-check | 7 pass, 2 weak, 1 fail |

Details and failure analysis: [`eval/results.md`](eval/results.md) and [`eval/spot_check.md`](eval/spot_check.md).

## Tests

```bash
pytest
```

The tests use a fake model, so they run offline in about a second. They cover the parser on format variants, the promo rules, ranking, the cache, JSON repair, a full pipeline run, the evaluation and the app.

## Data and confidentiality

The input pack is Kuku's confidential content. It is not in this repository (`data/` is git-ignored) and the hosted app does not contain it. - The cached replies in `raw/` store the model's answer and a hash of the prompt, never the screenplay text that was sent.
- Committed outputs contain timestamps, short hook and cliffhanger quotes, and model-written descriptions.
- One exception: the series bible (`bible.json`) and the judge's one-line summaries describe the plot. They are kept because the brief asks for unedited raw outputs on the full pack. If Kuku prefers otherwise, the repository can be made private, or `bible.json` and `raw/01_bible*` can be removed, without affecting anything else.

## Limitations

- It reads text only. It cannot judge acting, music or how visually striking a moment is, and screenplay timestamps may drift from the final cut.
- The generator and the judge are the same model family, so they may share blind spots. The baseline comparison and the manual spot-check in `eval/` are the counterweight.
- Spoiler detection is keyword-based against the series bible and will miss paraphrased reveals.
- An editor should review the list before posting. The app supports that with approve and export.
