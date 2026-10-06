"""Build dashboard/index.html: a self-contained dashboard (no libraries, opens offline).

Reads data/*.parquet (run src/build_data.py first), refits the notebook's joint models, and inlines the
results plus the 416 team-season rows into src/dashboard_template.html.

Model estimates match analysis.ipynb sections 2, 7 and 8:
  outcome ~ starter cap share (pp) for all 10 positions + special teams + dead money, bench spending as the reference,
  season fixed effects, standard errors clustered by team. "Robust" = how many of the 6 starter definitions
  keep the coefficient significant at 5%.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_data as bd  # noqa: E402
from build_data import BASE_CAP, BASELINE_RULE, OFFENSE, STARTER_RULES, assign_roles, share_table  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POS = ["QB", "RB", "WR", "TE", "OL", "DL", "EDGE", "LB", "CB", "S"]
DEAD = "DEAD"   # the 11th row: dead money + unspent cap, as a share of tracked cap (not a position)
ALL = POS + [DEAD]
CURRENT = 2026   # the season the outlook chart looks at (in progress: cap numbers as of now, starters from snaps so far)
OUTCOMES = {"pd": "pt_diff_pg", "off": "off", "dfn": "dfn", "fin": "finish"}  # dashboard key -> column
FLIPPED = {"fin"}  # finish is a rank (1 = best); estimates are shown as places GAINED so positive always means better
TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}


def load_outcomes(ts: pd.DataFrame) -> pd.DataFrame:
    out = ts[["season", "team", "pt_diff_pg", "win_pct"]].copy()
    out["off"] = ts["off_epa_play"] * 100       # EPA per 100 plays
    out["dfn"] = -ts["def_epa_play"] * 100      # flipped so higher = better defense
    out["finish"] = ts["finish"]                # overall finish: 1 = best ... 32 = worst (pre-trade first-round slot, flipped)
    return out


def with_shares(ps: pd.DataFrame, rule: dict, outcomes: pd.DataFrame, dead: pd.DataFrame) -> pd.DataFrame:
    p = ps.copy()
    p["role"] = assign_roles(p, rule)
    d = share_table(p).merge(outcomes, on=["season", "team"]).merge(dead, on=["season", "team"])
    d["DEAD_pp"] = d["dead_m"] / d["tracked_cap_m"] * 100
    for pos in POS:
        d[f"{pos}_st"] = d[f"{pos}_starter_share"] * 100
    d["ST_pct"] = d["ST_all_share"] * 100
    return d


def joint_fit(d: pd.DataFrame, y: str):
    rhs = " + ".join(f"{p}_st" for p in POS) + " + ST_pct + DEAD_pp"
    return smf.ols(f"{y} ~ {rhs} + C(season)", d).fit(cov_type="cluster", cov_kwds={"groups": d["team"]})


def load_current() -> tuple[pd.DataFrame, int]:
    """Cap + snaps for the in-progress season, built the same way as player_season.parquet (only the columns the roles need)."""
    first, last = bd.FIRST, bd.LAST
    bd.FIRST = bd.LAST = CURRENT
    try:
        cap, snaps = bd.load_cap(), bd.load_snap_share()
        weeks = int(bd.nfl.load_snap_counts([CURRENT]).to_pandas().query("game_type == 'REG'")["week"].max())
    finally:
        bd.FIRST, bd.LAST = first, last
    p = cap.merge(snaps, on=["gsis_id", "season"], how="left")
    cols = ["offense_snaps", "defense_snaps", "off_share", "def_share"]
    p[cols] = p[cols].fillna(0)
    p["unit_share"] = np.where(p["pos_group"].isin(OFFENSE), p["off_share"], np.where(p["pos_group"].isin(bd.DEFENSE), p["def_share"], np.nan))
    p["unit_snaps"] = np.where(p["pos_group"].isin(OFFENSE), p["offense_snaps"], p["defense_snaps"])
    p["snap_rank"] = p.groupby(["season", "team", "pos_group"])["unit_snaps"].rank(method="first", ascending=False)
    return p, weeks


def outlook(d_train: pd.DataFrame) -> dict | None:
    """What each team's current cap split predicts for the in-progress season, relative to the league-average team that season.

    Season effects are unknown for a new year, so the prediction is beta . (team's shares - league mean shares): the same
    deviation-from-average a season fixed effect would produce. Two models: all positions + dead money, and QB + dead money only
    (which predicted best on held-out seasons).
    """
    cur, weeks = load_current()
    if cur.empty:
        return None
    cur["role"] = assign_roles(cur, STARTER_RULES[BASELINE_RULE])
    w = share_table(cur)
    for pos in POS:
        w[f"{pos}_st"] = w[f"{pos}_starter_share"] * 100
    w["DEAD_pp"] = (BASE_CAP[CURRENT] - w["tracked_cap_m"]) / w["tracked_cap_m"] * 100
    w["ST_pct"] = w["ST_all_share"] * 100
    terms = [term_of(q) for q in ALL] + ["ST_pct"]   # the 12th term (special teams) is in the model but not shown as a row
    raw = w[terms].to_numpy()
    # never extrapolate: cap each input at the range the model was fit on (a team with far more dead money than any past team is flagged, not extrapolated)
    lo, hi = d_train[terms].min().to_numpy(), d_train[terms].max().to_numpy()
    x = np.clip(raw, lo, hi)
    capped = {t: [terms[j] for j in range(len(terms)) if raw[i, j] != x[i, j]] for i, t in enumerate(w["team"]) if (raw[i] != x[i]).any()}
    MODELS = {"full": terms, "qb": ["QB_st", "DEAD_pp"]}   # full = all positions + dead money + special teams
    out = {"season": CURRENT, "weeks": weeks, "asof": pd.Timestamp.today().strftime("%B %-d, %Y"), "teams": list(w["team"]),
           "x": [[round(float(v), 2) for v in row] for row in x], "raw": [[round(float(v), 1) for v in row] for row in raw],
           "capped": {t: [q.replace("_st", "").replace("_pp", "") for q in qs] for t, qs in capped.items()}, "usd": [round(float(v), 1) for v in w["tracked_cap_m"]],
           "models": {}}
    for mk, mterms in MODELS.items():
        out["models"][mk] = {}
        for key, col in OUTCOMES.items():
            rhs = " + ".join(mterms)
            m = smf.ols(f"{col} ~ {rhs} + C(season)", d_train).fit(cov_type="cluster", cov_kwds={"groups": d_train["team"]})
            sign = -1 if key in FLIPPED else 1
            coef = [sign * float(m.params[t]) if t in mterms else 0.0 for t in terms]
            V = m.cov_params()
            cov = [[float(V.loc[a, b]) if (a in mterms and b in mterms) else 0.0 for b in terms] for a in terms]
            out["models"][mk][key] = {"coef": [round(c, 4) for c in coef], "cov": [[round(v, 6) for v in r] for r in cov],
                                      "rsd": round(float(np.sqrt(m.mse_resid)), 2)}
    return out


def term_of(pos: str) -> str:
    return "DEAD_pp" if pos == DEAD else f"{pos}_st"


def main() -> None:
    ts = pd.read_parquet(ROOT / "data" / "team_season.parquet")
    ps = pd.read_parquet(ROOT / "data" / "player_season.parquet")
    outcomes = load_outcomes(ts)
    dead = ts[["season", "team", "dead_m"]]

    # robustness: significance of each coefficient under each starter definition
    term = lambda pos: "DEAD_pp" if pos == DEAD else f"{pos}_st"
    sig_count = {k: {p: 0 for p in ALL} for k in OUTCOMES}
    base = {}
    resid = {}   # per outcome: how far each team-season beat (+) or missed (-) what its spending predicts, in the outcome's own units
    for name, rule in STARTER_RULES.items():
        d = with_shares(ps, rule, outcomes, dead)
        for key, col in OUTCOMES.items():
            m = joint_fit(d, col)
            for pos in ALL:
                sig_count[key][pos] += int(m.pvalues[term(pos)] < 0.05)
            if name == BASELINE_RULE:
                ci, sign = m.conf_int(), (-1 if key in FLIPPED else 1)
                base[key] = {pos: {"coef": sign * m.params[term(pos)],
                                   "lo": min(sign * ci.loc[term(pos), 0], sign * ci.loc[term(pos), 1]),
                                   "hi": max(sign * ci.loc[term(pos), 0], sign * ci.loc[term(pos), 1]),
                                   "p": m.pvalues[term(pos)]} for pos in ALL}
                base[key]["_r2"] = m.rsquared
                d_base = d
                resid[key] = pd.Series(sign * m.resid.values, index=pd.MultiIndex.from_frame(d[["season", "team"]]))

    findings = {key: [{"pos": pos, **{k: round(float(v), 4) for k, v in base[key][pos].items()}, "robust": sig_count[key][pos]}
                      for pos in ALL] for key in OUTCOMES}

    # injury context for each team-season (roster IR data is thin before 2016): weeks the planned starting QB (highest cap) was on IR or inactive, and cap share on 4+ week IR players
    qbs = ps[ps["pos_group"] == "QB"].assign(out=lambda q: q["weeks_ir"] + q["weeks_ina"])
    qb1_ir = qbs.loc[qbs.groupby(["season", "team"])["cap_m"].idxmax()].set_index(["season", "team"])["out"]   # the planned starter = highest-cap QB
    ir_cap = ps[ps["weeks_ir"] >= 4].groupby(["season", "team"])["cap_m"].sum()
    rows = []
    d0 = ts.merge(outcomes[["season", "team", "off", "dfn"]], on=["season", "team"])
    for r in d0.itertuples():
        rows.append({"s": int(r.season), "t": r.team, "pd": round(r.pt_diff_pg, 2), "w": round(r.win_pct, 3),
                     "off": round(r.off, 2), "dfn": round(r.dfn, 2), "fin": int(r.finish), "rs": {k: round(float(resid[k].loc[(r.season, r.team)]), 2) for k in OUTCOMES},
                     "qi": int(qb1_ir.get((r.season, r.team), 0)) if r.season >= 2016 else None,
                     "ir": round(float(ir_cap.get((r.season, r.team), 0)) / r.tracked_cap_m * 100, 1) if r.season >= 2016 else None, "cap": round(r.tracked_cap_m, 1),
                     "st": [round(getattr(r, f"{p}_starter_share") * 100, 2) for p in POS] + [round(r.dead_m / r.tracked_cap_m * 100, 2)],
                     "usd": [round(getattr(r, f"{p}_starter"), 2) for p in POS] + [round(r.dead_m, 2)]})

    data = {"pos": ALL, "teams": TEAM_NAMES, "rows": rows, "findings": findings,
            "r2": {k: round(float(base[k]["_r2"]), 3) for k in OUTCOMES},
            "seasons": [int(ts.season.min()), int(ts.season.max())], "fc": outlook(d_base)}

    html = (Path(__file__).resolve().parent / "dashboard_template.html").read_text()
    assert "__DATA__" in html
    out = ROOT / "dashboard" / "index.html"
    out.write_text(html.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB); {len(rows)} team-seasons")


if __name__ == "__main__":
    main()
