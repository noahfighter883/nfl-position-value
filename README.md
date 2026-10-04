# Which NFL positions are worth paying for?

Team-level analysis of how salary-cap spending by position relates to team success, 2013–2025 (416 team-seasons).
Starters and bench players are separated using snap counts.

**Read the results:** [`analysis.ipynb`](analysis.ipynb) (outputs are saved, so it renders on GitHub).

## Headline findings
- **QB** is the clearest case: higher starter-QB spend goes with better point differential, with most of the gain by ~$19M. It holds after controlling for rookie-scale contracts, and in EPA terms it is entirely a *passing offense* effect. Money tied up in non-starting QBs and OL goes with worse results, but it turns out to be mostly *injured-reserve* money (a same-season injury effect), not wasted spending on depth.
- **Effects land where football says they should** (EPA/play split): QB, WR and OL (run game) help the offense; EDGE and CB (pass defense) and interior DL (run defense) help the defense. S and LB show nothing clear.
- **WR** looked flat on point differential but shows a modest real offensive-EPA effect.
- **TE** looked valuable at first, but TE spend also "predicts" *defensive* EPA, which fails a placebo test, so it is probably noise.
- **Insurance:** losing the starting QB for 8 weeks costs about 5 pts/game, but pricier backup QBs show no detectable cushion. The data rule out large benefits (a $5M backup recovers at most ~1/5 of the damage), not small ones.
- **Robust to the starter definition:** QB, WR, OL, EDGE and CB findings hold under six different definitions of "starter"; interior DL is weaker and TE is not stable.
- Cap allocation explains only ~10% of variance in point differential. This is association, not causation.

## Method (short)
- **Cap data:** per-player cap hits from Over the Cap, via `nflreadpy`. Cap share = position group's cap ÷ team's tracked cap.
- **Starter** = top-N at each position by snaps (QB1, RB1, WR3, TE1, OL5, DL2, EDGE2, LB2, CB3, S2); everyone else is bench.
- **Outcome:** regular-season point differential per game (win % as a robustness check).
- **Model:** OLS with season fixed effects, standard errors clustered by team, bench spending as the reference group.

## Reproduce
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/build_data.py          # writes data/*.parquet
jupyter nbconvert --to notebook --execute analysis.ipynb --output analysis.ipynb
```

## Caveats
Tracked cap is only part of the official cap (dead money and some players are missing), cap hit is an accounting number, a traded player's cap is assigned to one team, and 416 team-seasons is small for 10 positions at once. See the notebook's final section.
