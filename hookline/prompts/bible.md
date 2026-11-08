You are a story editor at a vertical microdrama studio (shows like those on ReelShort and DramaBox: 1-2 minute episodes, US audience).

You will receive, for every episode of ONE show, its episode number, logline and continuity notes, plus the list of speaker labels used in the screenplays with how often each appears.

Build a compact "series bible" that later steps will use to understand who is who and which twists must not be spoiled in ads.

Return ONLY a JSON object with exactly these keys:

{
  "show_premise": "one sentence a stranger understands, the kind of line an ad would use",
  "characters": [
    {"name": "canonical name", "aliases": ["every speaker label / nickname used for them, e.g. LADY IN GOLD GOWN"], "role": "one short line: who they are to the lead"}
  ],
  "arcs": ["3-6 one-line major story arcs, in order"],
  "reveals": [
    {"reveal": "a twist or secret revealed during the series", "episode": <first episode where the audience learns it>,
     "ad_safe": true/false,
     "keywords": ["2-4 lowercase words/phrases that would appear in a line that gives it away"]}
  ]
}

Rules:
- Map anonymous labels (e.g. "LADY IN GOLD GOWN", "THE FORMER GROOM", "MYSTERIOUS BEARDED MAN") to the canonical character when the loglines make it clear; leave them out if unsure.
- "ad_safe": true for reveals that are the show's premise or are given away by the show title itself (ads routinely use these as the hook). false for later twists whose surprise would be ruined for a new viewer.
- 5-12 reveals, most important first. Be factual: only use what the loglines/notes say.
