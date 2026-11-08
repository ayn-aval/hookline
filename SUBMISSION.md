# Submission checklist

Submit one form through the placement cell before the deadline.

## Form fields

| Field | Value |
|---|---|
| Name | Lavanya L Nair |
| Roll number | (fill in) |
| Branch | Biochemical Engineering, IIT (BHU) Varanasi (please verify) |
| Problem chosen | Problem 1: Find the Promos (Ads) |
| Solution doc (PDF, 2 pages) | https://github.com/ayn-aval/hookline/blob/main/docs/solution.pdf |
| Prototype link | https://hookline-promos.streamlit.app (code: https://github.com/ayn-aval/hookline) |
| Raw outputs | https://github.com/ayn-aval/hookline/tree/main/outputs/i-married-a-broken-soldier |
| Walkthrough video (optional) | Record using `docs/walkthrough_script.md`, upload as unlisted, and paste the link |

## Before submitting

- [ ] Open every link in a private (incognito) window and confirm it loads without signing in.
- [ ] Read `docs/solution.pdf` end to end and change anything that is not in your own words or that you disagree with. The interview will go through these decisions.
- [ ] Optional: add the demo key to the app, so visitors can run it on a new show without their own key. Go to share.streamlit.io, open the app's ⋮ menu, choose Settings, then Secrets, and paste `GEMINI_API_KEY = "..."`.
- [ ] Optional, after the free quota resets: re-run with the stronger model and compare.
  `python -m hookline run --input data --out outputs/flash-run --model gemini-3.5-flash --env-file ../.env.hookline`

## Before the interview (you will run it on a new show)

```bash
git clone https://github.com/ayn-aval/hookline.git && cd hookline
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
export GEMINI_API_KEY=...            # or the key/endpoint Kuku provides
python -m hookline run --input path/to/new-show --out outputs/new-show
python -m hookline run --input path/to/new-show --out outputs/new-show-x \
  --provider custom --base-url https://their-endpoint/v1 --model their-model --judge-model their-model
```

The input pack is confidential. Do not upload it anywhere public; this repository excludes it via `.gitignore`.
