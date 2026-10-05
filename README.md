# Which NFL positions are worth paying for?

Team-level analysis of how salary-cap spending by position relates to team success, 2013–2025 (416 team-seasons).
Starters and bench players are separated using snap counts.

**Read the results:** [`analysis.ipynb`](analysis.ipynb) (outputs are saved, so it renders on GitHub).

**Read the story:** [`WRITEUP.md`](WRITEUP.md) is a short case study of the question, method, findings and limits.

**Explore them:** open [`dashboard/index.html`](dashboard/index.html) in a browser. It is one self-contained file (no server or libraries) with a findings chart, a position explorer (with a team highlight dropdown), and a team explorer. Four outcomes can be switched in the charts: point differential, offense EPA, defense EPA, and overall finish. An eleventh row, dead money and unspent cap, sits beside the ten positions in every chart. Numbers come from the same data and models as the notebook.

## Headline findings
- **QB** is the clearest case: higher starter-QB spend goes with better point differential, with most of the gain by ~$19M. It holds after controlling for rookie-scale contracts, and in EPA terms it is entirely a *passing offense* effect. Money tied up in non-starting QBs and OL goes with worse results, but it turns out to be mostly *injured-reserve* money (a same-season injury effect), not wasted spending on depth. Returns taper off above roughly 14% of the cap (about $30M+ today); a decline at the very top is possible but not established.
- **Effects land where football says they should** (EPA/play split): QB, WR and OL (run game) help the offense; EDGE and CB (pass defense) and interior DL (run defense) help the defense. S and LB show nothing clear.
- **WR** looked flat on point differential but shows a modest real offensive-EPA effect.
- **TE** looked valuable at first, but TE spend also "predicts" *defensive* EPA, which fails a placebo test, so it is probably noise.
- **Insurance:** losing the starting QB for 8 weeks costs about 5 pts/game. A better replacement QB should recover only a small share (about a fifth of the damage per standard deviation of quality, both as measured and as expected from the mechanics), and the data cannot distinguish that from zero. This holds whether quality is measured by cap hit, prior EPA, experience, draft pick, or the QB who actually played, and with a prior calibrated to replacement level.
- **Robust to the starter definition:** QB, WR, OL, EDGE and CB findings hold under six different definitions of "starter"; interior DL is weaker and TE is not stable.
- Cap allocation explains only ~10% of variance in point differential. This is association, not causation.

## Method (short)
- **Cap data:** per-player cap hits from Over the Cap, via `nflreadpy`. Cap share = position group's cap ÷ team's tracked cap.
- **Starter** = top-N at each position by snaps (QB1, RB1, WR3, TE1, OL5, DL2, EDGE2, LB2, CB3, S2); everyone else is bench.
- **Outcomes:** regular-season point differential per game, offensive and defensive EPA per play, and **overall finish** (1 = champion ... 32 = worst, read from each team's original pre-trade first-round draft slot, so it includes playoff results).
- **Model:** OLS with season fixed effects, standard errors clustered by team, bench spending as the reference group.

## Reproduce
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/build_data.py          # writes data/*.parquet
python src/build_dashboard.py     # writes dashboard/index.html from src/dashboard_template.html
jupyter nbconvert --to notebook --execute analysis.ipynb --output analysis.ipynb
```

## Caveats
Tracked cap is only part of the official cap, and dead money is missing from the contract data (it is recovered as base cap minus tracked cap, which also includes unspent cap), cap hit is an accounting number, a traded player's cap is assigned to one team, and 416 team-seasons is small for 10 positions plus dead money at once. See the notebook's final section.
