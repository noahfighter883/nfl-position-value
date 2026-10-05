"""Build dashboard/index.html: a self-contained dashboard (no libraries, opens offline).

Reads data/*.parquet (run src/build_data.py first), refits the notebook's joint models, and inlines the
results plus the 416 team-season rows into src/dashboard_template.html.

Model estimates match analysis.ipynb sections 2, 7 and 8:
  outcome ~ starter cap share (pp) for all 10 positions + special teams, bench spending as the reference,
  season fixed effects, standard errors clustered by team. "Robust" = how many of the 6 starter definitions
  keep the coefficient significant at 5%.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_data import BASELINE_RULE, STARTER_RULES, assign_roles, share_table  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POS = ["QB", "RB", "WR", "TE", "OL", "DL", "EDGE", "LB", "CB", "S"]
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


def with_shares(ps: pd.DataFrame, rule: dict, outcomes: pd.DataFrame) -> pd.DataFrame:
    p = ps.copy()
    p["role"] = assign_roles(p, rule)
    d = share_table(p).merge(outcomes, on=["season", "team"])
    for pos in POS:
        d[f"{pos}_st"] = d[f"{pos}_starter_share"] * 100
    d["ST_pct"] = d["ST_all_share"] * 100
    return d


def joint_fit(d: pd.DataFrame, y: str):
    rhs = " + ".join(f"{p}_st" for p in POS) + " + ST_pct"
    return smf.ols(f"{y} ~ {rhs} + C(season)", d).fit(cov_type="cluster", cov_kwds={"groups": d["team"]})


def main() -> None:
    ts = pd.read_parquet(ROOT / "data" / "team_season.parquet")
    ps = pd.read_parquet(ROOT / "data" / "player_season.parquet")
    outcomes = load_outcomes(ts)

    # robustness: significance of each coefficient under each starter definition
    sig_count = {k: {p: 0 for p in POS} for k in OUTCOMES}
    base = {}
    for name, rule in STARTER_RULES.items():
        d = with_shares(ps, rule, outcomes)
        for key, col in OUTCOMES.items():
            m = joint_fit(d, col)
            for pos in POS:
                sig_count[key][pos] += int(m.pvalues[f"{pos}_st"] < 0.05)
            if name == BASELINE_RULE:
                ci, sign = m.conf_int(), (-1 if key in FLIPPED else 1)
                base[key] = {pos: {"coef": sign * m.params[f"{pos}_st"],
                                   "lo": min(sign * ci.loc[f"{pos}_st", 0], sign * ci.loc[f"{pos}_st", 1]),
                                   "hi": max(sign * ci.loc[f"{pos}_st", 0], sign * ci.loc[f"{pos}_st", 1]),
                                   "p": m.pvalues[f"{pos}_st"]} for pos in POS}
                base[key]["_r2"] = m.rsquared

    findings = {key: [{"pos": pos, **{k: round(float(v), 4) for k, v in base[key][pos].items()}, "robust": sig_count[key][pos]}
                      for pos in POS] for key in OUTCOMES}

    rows = []
    d0 = ts.merge(outcomes[["season", "team", "off", "dfn"]], on=["season", "team"])
    for r in d0.itertuples():
        rows.append({"s": int(r.season), "t": r.team, "pd": round(r.pt_diff_pg, 2), "w": round(r.win_pct, 3),
                     "off": round(r.off, 2), "dfn": round(r.dfn, 2), "fin": int(r.finish), "cap": round(r.tracked_cap_m, 1),
                     "st": [round(getattr(r, f"{p}_starter_share") * 100, 2) for p in POS],
                     "usd": [round(getattr(r, f"{p}_starter"), 2) for p in POS]})

    data = {"pos": POS, "teams": TEAM_NAMES, "rows": rows, "findings": findings,
            "r2": {k: round(float(base[k]["_r2"]), 3) for k in OUTCOMES},
            "seasons": [int(ts.season.min()), int(ts.season.max())]}

    html = (Path(__file__).resolve().parent / "dashboard_template.html").read_text()
    assert "__DATA__" in html
    out = ROOT / "dashboard" / "index.html"
    out.write_text(html.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB); {len(rows)} team-seasons")


if __name__ == "__main__":
    main()
