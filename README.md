# Which NFL positions are worth paying for?

Team-level analysis of how salary-cap spending by position relates to team success, 2013–2025 (416 team-seasons).
Starters and bench players are separated using snap counts.

**Read the results:** [`analysis.ipynb`](analysis.ipynb) (outputs are saved, so it renders on GitHub).

## Headline findings
- **QB** is the clearest case: higher starter-QB spend goes with better point differential, with most of the gain by ~$19M. This holds after controlling for rookie-scale contracts (the coefficient is essentially unchanged, and holds within both rookie-deal and veteran-deal QBs). Money spent on non-starting QBs is associated with *worse* results.
- **WR** spend shows no payoff beyond a modest level; neither the top-paid WR nor the other starters stand out.
- **TE** (small sample, wide interval) and **OL outside the top five** are surprises worth digging into.
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
