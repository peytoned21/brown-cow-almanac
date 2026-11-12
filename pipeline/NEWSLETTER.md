# The weekly newsletter

Each Tuesday after the refresh, a scheduled Claude task writes one issue per league from that league's fact sheet, then publishes it to the site.

## How an issue gets made

1. `python3 pipeline/newsletter_facts.py leagues/<league>.json > /tmp/facts.json`. This is the only source. Read it all before writing.
2. Write the issue as JSON (format below) to `/tmp/issue.json`.
3. `python3 pipeline/newsletter_publish.py leagues/<league>.json /tmp/issue.json`. This checks the issue, and refuses it if a number doesn't appear in the fact sheet. It then saves the issue to `<league dir>/newsletter/` and updates that folder's index.
4. Commit and push. For Brown Cow, dispatch the `post.yml` workflow with `league=brown-cow` and `kind=newsletter` to post it to GroupMe.

## Format

```json
{
  "y": 2026, "wk": 8,
  "title": "Short, punchy headline (under 70 characters)",
  "dek": "One sentence under the headline that says what happened.",
  "sections": [
    {"head": "The lead", "body": ["paragraph", "paragraph"]},
    {"head": "Around the league", "body": ["..."]},
    {"head": "Power shifts", "body": ["..."]},
    {"head": "The playoff picture", "body": ["..."]},
    {"head": "Game of the Week", "body": ["..."]},
    {"head": "Award watch", "body": ["..."]}
  ],
  "groupme": "A teaser for the league chat, under 600 characters, ending on a hook. No link (one is added)."
}
```

Use 4–6 sections, with 1–3 short paragraphs each. Aim for 450–650 words in total. You may use `**bold**` for emphasis, at most once per paragraph.

## Voice

- Write like the league's own columnist: dry, specific and affectionate, a little ruthless about bad lineup decisions. It should read like a smart friend who watched every game. It should not read like a press release, and it should not sound like an AI.
- **Lead with the best story of the week, not the order of the games.** Good leads: an upset, a streak, a huge swing in someone's playoff odds, a rivalry result, a blowout or a heartbreaker.
- Use managers' short names as the fact sheet gives them (Peyton, Chris & Miguel). Use team names now and then, for color.
- Every claim comes from the fact sheet. Don't invent players' stats, quotes, injuries, trades or history. If the fact sheet doesn't say something, don't say it.
- Numbers: scores to one decimal, odds as whole percents, records as 8–0. Only use numbers that appear in the fact sheet. You may convert a probability to a percent, and you may give the change in a team's playoff odds from last week.
- When `thisWeek.comebackOfTheWeek` is there, it's usually the lead or close to it: the winner's lowest win chance, and when (from the game-day replay). `thisWeek.biggestSwingPlays` lists the single plays that moved a matchup most; name the player and the play as given ("Bijan Robinson's 57-yd TD run") and the swing in win chance as a whole percent. When `replayLink` is there, you may tell readers the replays are on the site.
- `powerRatings` is the league's best guess at who is actually good, in points per week vs an average team. The interesting stories are where it disagrees with the record (a 9–0 team rated third, a 2–7 team rated fourth). Quote ratings to one decimal with a sign (+5.7).
- Look ahead to next week: the Game of the Week, what's at stake in the playoff race, and an all-time series when it's lopsided or tied.
- No emoji in the issue. One emoji at most in the GroupMe teaser.
- Avoid clichés: "statement win", "when the dust settled", "it's anyone's game", "buckle up". Avoid stacked adjectives, and don't use rhetorical questions to open sections.

## Season over

If the fact sheet says `seasonOver`, write a short champion's issue with a single section instead.
