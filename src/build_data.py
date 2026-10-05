"""Build the team-season analysis table: cap $ by position group (starter vs. bench) + results.

Sources (all via nflreadpy / nflverse):
  - contracts: Over the Cap per-player, per-year cap numbers (season_history)
  - snap counts: PFR, 2013+
  - schedules: game results

Outputs to data/:
  player_season.parquet  one row per player-team-season: position group, cap $M, snap share, starter flag
  team_season.parquet    one row per team-season: cap $M and share by position group x role, plus results
  qb_season.parquet      one row per passer-season: regular-season pass plays and total EPA
"""
from pathlib import Path

import nflreadpy as nfl
import numpy as np
import pandas as pd

FIRST, LAST = 2013, 2025  # snap counts start in 2013
# starters = the top-N players at each position group by snaps played (N fills a base 11-man lineup);
# a flat snap-share cutoff undercounts starters at positions that rotate (RB, DL, LB)
STARTER_SLOTS = {"QB": 1, "RB": 1, "WR": 3, "TE": 1, "OL": 5, "DL": 2, "EDGE": 2, "LB": 2, "CB": 3, "S": 2}
BASELINE_RULE = "top-N (base 11)"
# alternative starter definitions, used by the sensitivity check in the notebook
STARTER_RULES = {
    BASELINE_RULE: {"slots": STARTER_SLOTS},
    "top-N narrow": {"slots": {"QB": 1, "RB": 1, "WR": 2, "TE": 1, "OL": 5, "DL": 2, "EDGE": 2, "LB": 1, "CB": 2, "S": 2}},
    "top-N wide": {"slots": {"QB": 1, "RB": 2, "WR": 4, "TE": 2, "OL": 6, "DL": 3, "EDGE": 3, "LB": 3, "CB": 4, "S": 3}},
    "snap share >= 33%": {"share": 0.33},
    "snap share >= 50%": {"share": 0.50},
    "snap share >= 66%": {"share": 0.66},
}
OUT = Path(__file__).resolve().parent.parent / "data"

NICKNAME_TO_ABBR = {
    "49ers": "SF", "Bears": "CHI", "Bengals": "CIN", "Bills": "BUF", "Broncos": "DEN",
    "Browns": "CLE", "Buccaneers": "TB", "Cardinals": "ARI", "Chargers": "LAC", "Chiefs": "KC",
    "Colts": "IND", "Commanders": "WAS", "Cowboys": "DAL", "Dolphins": "MIA", "Eagles": "PHI",
    "Falcons": "ATL", "Giants": "NYG", "Jaguars": "JAX", "Jets": "NYJ", "Lions": "DET",
    "Packers": "GB", "Panthers": "CAR", "Patriots": "NE", "Raiders": "LV", "Rams": "LA",
    "Ravens": "BAL", "Redskins": "WAS", "Saints": "NO", "Seahawks": "SEA", "Steelers": "PIT",
    "Texans": "HOU", "Titans": "TEN", "Vikings": "MIN", "Washington": "WAS",
}
# relocations: collapse to the current franchise abbreviation
ABBR_FIX = {"OAK": "LV", "SD": "LAC", "STL": "LA"}

POS_GROUP = {
    "QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE",
    "LT": "OL", "LG": "OL", "C": "OL", "RG": "OL", "RT": "OL",
    "IDL": "DL", "ED": "EDGE", "LB": "LB", "CB": "CB", "S": "S",
    "K": "ST", "P": "ST", "LS": "ST",
}
OFFENSE = {"QB", "RB", "WR", "TE", "OL"}
DEFENSE = {"DL", "EDGE", "LB", "CB", "S"}


def load_cap() -> pd.DataFrame:
    c = nfl.load_contracts().to_pandas()
    players = nfl.load_players().to_pandas()
    # a few contracts lack gsis_id; recover it from the otc_id crosswalk
    otc_to_gsis = players.dropna(subset=["otc_id", "gsis_id"]).drop_duplicates("otc_id").set_index("otc_id")["gsis_id"]
    c["gsis_id"] = c["gsis_id"].fillna(c["otc_id"].map(otc_to_gsis))

    rows = []
    for p in c.itertuples():
        for d in (p.season_history if p.season_history is not None else []):
            rows.append({"otc_id": p.otc_id, "gsis_id": p.gsis_id, "player": p.player,
                         "position": p.position, "year": d["year"], "team": d["team"],
                         "cap_number": d["cap_number"], "draft_year": p.draft_year,
                         "draft_round": p.draft_round, "draft_overall": p.draft_overall})
    df = pd.DataFrame(rows)
    df["season"] = pd.to_numeric(df["year"], errors="coerce")
    df = df[df["season"].between(FIRST, LAST)].copy()
    df["season"] = df["season"].astype(int)
    # each player's full history is repeated on every contract row; keep one copy
    df = df.drop_duplicates(["otc_id", "season", "team"])
    df["team"] = df["team"].map(NICKNAME_TO_ABBR)
    df["pos_group"] = df["position"].map(POS_GROUP)
    df = df.dropna(subset=["team", "pos_group", "cap_number"])
    df["cap_m"] = df["cap_number"].astype(float)
    return df[["otc_id", "gsis_id", "player", "position", "pos_group", "season", "team", "cap_m",
               "draft_year", "draft_round", "draft_overall"]]


def load_snap_share() -> pd.DataFrame:
    """Per player-season: share of his primary team's offensive/defensive snaps (regular season)."""
    players = nfl.load_players().to_pandas()
    pfr_to_gsis = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id")["gsis_id"]
    s = nfl.load_snap_counts(list(range(FIRST, LAST + 1))).to_pandas()
    s = s[s["game_type"] == "REG"].copy()
    s["team"] = s["team"].replace(ABBR_FIX)
    s["gsis_id"] = s["pfr_player_id"].map(pfr_to_gsis)
    s = s.dropna(subset=["gsis_id"])

    # team snaps per game = the most snaps any one player had that game (someone plays nearly every snap)
    tg = s.groupby(["game_id", "team"]).agg(off=("offense_snaps", "max"), dfn=("defense_snaps", "max")).reset_index()
    team_season = tg.merge(s[["game_id", "season"]].drop_duplicates(), on="game_id") \
                    .groupby(["season", "team"])[["off", "dfn"]].sum().reset_index() \
                    .rename(columns={"off": "team_off", "dfn": "team_def"})

    ps = s.groupby(["gsis_id", "season", "team"])[["offense_snaps", "defense_snaps"]].sum().reset_index()
    ps["total"] = ps["offense_snaps"] + ps["defense_snaps"]
    ps = ps.sort_values("total", ascending=False).drop_duplicates(["gsis_id", "season"])  # primary team
    ps = ps.merge(team_season, on=["season", "team"])
    ps["off_share"] = ps["offense_snaps"] / ps["team_off"]
    ps["def_share"] = ps["defense_snaps"] / ps["team_def"]
    return ps[["gsis_id", "season", "offense_snaps", "defense_snaps", "off_share", "def_share"]]


def load_results() -> pd.DataFrame:
    g = nfl.load_schedules(list(range(FIRST, LAST + 1))).to_pandas()
    g = g[(g["game_type"] == "REG") & g["home_score"].notna()].copy()
    home = g.rename(columns={"home_team": "team", "home_score": "pf", "away_score": "pa"})
    away = g.rename(columns={"away_team": "team", "away_score": "pf", "home_score": "pa"})
    games = pd.concat([home[["season", "team", "pf", "pa"]], away[["season", "team", "pf", "pa"]]])
    games["team"] = games["team"].replace(ABBR_FIX)
    games["win"] = np.select([games.pf > games.pa, games.pf == games.pa], [1.0, 0.5], 0.0)
    r = games.groupby(["season", "team"]).agg(games=("win", "size"), wins=("win", "sum"),
                                              pf=("pf", "sum"), pa=("pa", "sum")).reset_index()
    r["win_pct"] = r["wins"] / r["games"]
    r["pt_diff_pg"] = (r["pf"] - r["pa"]) / r["games"]
    return r


def load_epa() -> pd.DataFrame:
    """Regular-season EPA/play per team-season: offense, and EPA allowed by the defense, split pass/rush."""
    frames = []
    for season in range(FIRST, LAST + 1):  # one season at a time: the full pbp table is large
        d = nfl.load_pbp([season]).select(["season", "season_type", "posteam", "defteam", "epa", "play_type"]).to_pandas()
        d = d[(d["season_type"] == "REG") & d["play_type"].isin(["pass", "run"]) & d["epa"].notna()]
        frames.append(d.drop(columns="season_type"))
    d = pd.concat(frames)
    d[["posteam", "defteam"]] = d[["posteam", "defteam"]].replace(ABBR_FIX)

    def per_play(side: str, prefix: str) -> pd.DataFrame:
        g = d.groupby(["season", side])
        out = pd.DataFrame({f"{prefix}_epa_play": g["epa"].mean()})
        for kind, label in (("pass", "pass"), ("run", "rush")):
            out[f"{prefix}_{label}_epa_play"] = d[d["play_type"] == kind].groupby(["season", side])["epa"].mean()
        return out.rename_axis(["season", "team"]).reset_index()

    # "def" = EPA the defense allowed per play (lower is better)
    return per_play("posteam", "off").merge(per_play("defteam", "def"), on=["season", "team"])


def load_availability() -> pd.DataFrame:
    """Regular-season weeks per player-season by roster status: active, inactive (game-day), injured lists."""
    r = nfl.load_rosters_weekly(list(range(FIRST, LAST + 1))).select(["season", "week", "gsis_id", "status", "game_type"]).to_pandas()
    r = r[(r["game_type"] == "REG") & r["gsis_id"].notna()].drop_duplicates(["season", "week", "gsis_id"])
    r["bucket"] = r["status"].map({"ACT": "weeks_act", "INA": "weeks_ina", "RES": "weeks_ir", "PUP": "weeks_ir", "NWT": "weeks_ir"})
    r["bucket"] = r["bucket"].fillna("weeks_other")  # practice squad (DEV), cut, suspended, etc.
    return r.pivot_table(index=["gsis_id", "season"], columns="bucket", values="week", aggfunc="count", fill_value=0).reset_index()


def load_qb_passing() -> pd.DataFrame:
    """Per passer-season: regular-season pass plays (sacks included) and total EPA."""
    frames = []
    for season in range(FIRST, LAST + 1):
        d = nfl.load_pbp([season]).select(["season", "season_type", "play_type", "passer_player_id", "epa"]).to_pandas()
        d = d[(d["season_type"] == "REG") & (d["play_type"] == "pass") & d["epa"].notna() & d["passer_player_id"].notna()]
        frames.append(d.groupby(["passer_player_id", "season"])["epa"].agg(pass_plays="size", epa_sum="sum").reset_index())
    return pd.concat(frames).rename(columns={"passer_player_id": "gsis_id"})


def assign_roles(ps: pd.DataFrame, rule: dict) -> pd.Series:
    """'starter' / 'bench' per player-season under a starter rule ({'slots': {pos: N}} or {'share': cutoff}).

    Specialists (K/P/LS) are one 'ST' bucket with no split; zero-snap players can never be starters.
    """
    if "slots" in rule:
        is_starter = ps["snap_rank"] <= ps["pos_group"].map(rule["slots"])
    else:
        is_starter = ps["unit_share"] >= rule["share"]
    return pd.Series(np.where(ps["pos_group"] == "ST", "all",
                              np.where(is_starter & (ps["unit_snaps"] > 0), "starter", "bench")), index=ps.index)


def share_table(ps: pd.DataFrame) -> pd.DataFrame:
    """Team-season cap $M and share of tracked cap by position group x role (uses ps['role'])."""
    wide = ps.pivot_table(index=["season", "team"], columns=["pos_group", "role"], values="cap_m",
                          aggfunc="sum", fill_value=0.0)
    wide.columns = [f"{g}_{r}" for g, r in wide.columns]
    wide = wide.reset_index()
    cap_cols = [c for c in wide.columns if c not in ("season", "team")]
    wide["tracked_cap_m"] = wide[cap_cols].sum(axis=1)
    for col in cap_cols:
        wide[f"{col}_share"] = wide[col] / wide["tracked_cap_m"]
    return wide


def main() -> None:
    OUT.mkdir(exist_ok=True)
    cap, snaps, results = load_cap(), load_snap_share(), load_results()

    ps = cap.merge(snaps, on=["gsis_id", "season"], how="left")
    ps[["offense_snaps", "defense_snaps", "off_share", "def_share"]] = \
        ps[["offense_snaps", "defense_snaps", "off_share", "def_share"]].fillna(0)
    ps["unit_share"] = np.where(ps["pos_group"].isin(OFFENSE), ps["off_share"],
                         np.where(ps["pos_group"].isin(DEFENSE), ps["def_share"], np.nan))
    avail = load_availability()
    ps = ps.merge(avail, on=["gsis_id", "season"], how="left")
    avail_cols = [c for c in avail.columns if c.startswith("weeks_")]
    ps[avail_cols] = ps[avail_cols].fillna(0)
    ps["unit_snaps"] = np.where(ps["pos_group"].isin(OFFENSE), ps["offense_snaps"], ps["defense_snaps"])
    ps["snap_rank"] = ps.groupby(["season", "team", "pos_group"])["unit_snaps"].rank(method="first", ascending=False)
    ps["role"] = assign_roles(ps, STARTER_RULES[BASELINE_RULE])
    # rookie-scale contract: drafted, within 4 seasons of the draft (5 for 1st-rounders: fifth-year option)
    yrs_since_draft = ps["season"] - ps["draft_year"]
    ps["rookie_deal"] = (ps["draft_round"].notna()
                         & (yrs_since_draft <= np.where(ps["draft_round"] == 1, 4, 3))
                         & (yrs_since_draft >= 0))
    ps.to_parquet(OUT / "player_season.parquet", index=False)

    wide = share_table(ps)

    qb1 = ps[(ps["pos_group"] == "QB") & (ps["role"] == "starter")] \
        .rename(columns={"rookie_deal": "qb1_rookie_deal", "draft_overall": "qb1_draft_overall", "cap_m": "qb1_cap_m"}) \
        [["season", "team", "qb1_rookie_deal", "qb1_draft_overall", "qb1_cap_m"]]
    wide = wide.merge(qb1, on=["season", "team"], how="left")

    ts = wide.merge(results, on=["season", "team"], how="inner").merge(load_epa(), on=["season", "team"], how="left")
    ts.to_parquet(OUT / "team_season.parquet", index=False)
    load_qb_passing().to_parquet(OUT / "qb_season.parquet", index=False)

    print(f"player_season: {len(ps):,} rows | team_season: {len(ts)} rows "
          f"({ts.season.min()}-{ts.season.max()}, {ts.team.nunique()} teams)")
    print(f"cap rows with a snap match: {(ps.offense_snaps + ps.defense_snaps > 0).mean():.1%}")
    print(f"team-seasons with a QB1 identified: {ts.qb1_cap_m.notna().sum()} / {len(ts)}; "
          f"QB1 on rookie deal: {ts.qb1_rookie_deal.fillna(False).astype(bool).sum()}")


if __name__ == "__main__":
    main()
