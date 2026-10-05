# Which NFL positions are worth paying for?

A team-level look at salary cap spending and results across 13 seasons (2013 to 2025). The interactive dashboard is at https://nfl-position-value.vercel.app.

## The short version

Spending on the starting quarterback has the clearest payoff in this data, and it works through the passing game. Receivers, offensive linemen, edge rushers and cornerbacks also pay off, on the side of the ball where they play. Tight end looks valuable at first, but a simple check says that result is probably noise. Taken together, how a team splits its cap explains only about a tenth of how it performs.

## The question

Every team splits a salary cap across positions, and the cap has grown a lot over this period (the average team's tracked cap rose from about $107M to $228M). Where is the next dollar worth the most? People argue about it all the time, usually with a handful of memorable examples. I wanted to check it against every team and season I could get.

## What I did

I combined public nflverse data into 416 team-seasons (32 teams, 2013 to 2025): contract cap hits from Over the Cap, snap counts, game results, play-by-play EPA and weekly roster status.

- **Cap share.** Each position group's cap hit as a share of the team's total, so a 2013 season can be compared with a 2025 one. One point of share is about $1.6M for an average team.
- **Starters and bench.** Money on a starting left tackle and money on a backup are different decisions. I counted the top players at each position by snaps as starters (QB1, RB1, three WR, TE1, five OL, and so on, filling a standard 11-man lineup) and everyone else as bench.
- **Results.** Point differential per game, plus offensive and defensive EPA per play, which separates the two sides of the ball.
- **One model for all positions.** A single regression with every position at once, season fixed effects, and standard errors clustered by team. Each coefficient answers one question: what happens if one point of cap moves from bench depth into this position's starters?

## What I found

### Quarterback is the clearest payoff

![Estimated effect of starter spending by position](writeup/img/01_position_effects.png)

Moving one point of cap share into the starting QB is associated with about +0.31 points per game (95% interval +0.21 to +0.41). In EPA terms the effect is almost entirely passing (+0.57 per 100 plays on pass offense, against +0.02 on the run game) and nothing on defense.

I worried about two things. Cheap rookie-contract QBs are a big group (44% of team-seasons), and if they happened to be worse, QB spending would only be standing in for age. Adding a rookie-contract control moved the QB coefficient from 0.234 to 0.240. I also reran the result under six different definitions of "starter", and the QB effect held under all six.

### Spending lines up with where the work happens

![Offense and defense effects](writeup/img/02_offense_vs_defense.png)

Splitting results into offense and defense, spending on offensive starters shows up in offensive EPA and spending on defensive starters shows up in defensive EPA. Receivers (+0.29) and offensive linemen (+0.34) help the offense, with the line's effect coming through the run game. Edge rushers (+0.24) and cornerbacks (+0.34) help the defense through pass defense, and interior linemen (+0.18) help against the run. Safeties and linebackers show no clear effect. All figures are EPA per 100 plays for one point of cap share.

### The tight end result that was not real

Tight end had the largest estimate in the first model, and it was stable across starter definitions. Then I ran a placebo check. Spending on offensive positions should not move the defense, and spending on defensive positions should not move the offense. Every position passed except one. Tight end spending "improved" the defense (+0.42, p = 0.007) about as much as it improved the offense. A tight end cannot cause that. I treat the original result as noise, or as a stand-in for something I did not measure. Stability across definitions did not save it, because the same quirk was present in every version.

### QB spending tapers off

The payoff per extra dollar falls as a QB's share of the cap rises. A curve fitted to the data peaks near 14% of the cap (roughly $30M to $35M at today's levels) and eases afterward. The top tier includes superstar seasons and big misses: 42% of the 59 team-seasons above 15% of the cap had a negative point differential. Whether returns actually turn negative at the top is not established, because the interval on the drop includes zero.

![Estimated payoff curve for QB spending](writeup/img/03_qb_payoff_curve.png)

### Most "wasted" bench money was injuries

Early on, money tied up in non-starting QBs and linemen looked wasteful, since it went with worse results. Splitting it by why the player was not a starter changed the story. Most of it was injured-reserve money. A one-standard-deviation increase in injured-reserve cap share costs about 1.2 points per game in the same season, but last season's injured-reserve money does not predict this season's results. That pattern fits an injury that hurt one team in one year. A badly built roster would carry over.

### Do better backup quarterbacks cushion the blow?

Losing the starting QB for eight weeks costs about five points per game. I tested whether a better backup softens that, measuring "better" several ways: cap hit, performance before the season (which I checked does predict next-year performance), experience and draft position. I also looked at the QB who actually replaced the starter, because the planned backup played only 53% of the time. The best estimate is that a replacement one standard deviation better recovers about a fifth of the damage, which is close to what the arithmetic predicts. The data cannot tell that from zero, and they cannot rule out a benefit of up to about two-fifths.

## What I would be careful about

- **Association, not causation.** Teams choose where to spend, and good teams may pay stars because they are good.
- **Cap hit is an accounting number.** Restructures and late-contract spikes inflate it, so it is an imperfect measure of what a player costs.
- **Partial coverage.** The cap data covers part of the official cap, so I use shares.
- **Small samples at the edges.** There are 59 team-seasons at the top of QB spending and about 76 seasons where the starter missed four or more weeks.
- **Many comparisons.** Ten positions across several outcomes means a few significant results are expected by chance. The pattern across results is what gives me confidence, more than any single p-value.

## How I checked myself

- Reran the key findings under six definitions of "starter".
- Controlled for rookie-scale contracts.
- Added the offense-versus-defense placebo test, which is what caught the tight end result.
- Used last season's values to separate injury effects from roster quality.
- Recalibrated my QB quality measure after finding that replacements played worse than it predicted.
- Caught two of my own bugs by comparing against numbers I already trusted: a units mix-up that briefly made a QB rating correlate negatively with results, and a chart whose labels had been overwritten.

## Built with

Python (pandas, statsmodels) in a Jupyter notebook. The dashboard is a single HTML file with hand-built SVG charts, generated from the same models and deployed on Vercel.

*Code and notebook: [link to add when the repository is public].*
