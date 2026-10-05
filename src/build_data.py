"""Build the team-season analysis table: cap $ by position group (starter vs. bench) + results.

Sources (all via nflreadpy / nflverse):
  - contracts: Over the Cap per-player, per-year cap numbers (season_history)
  - snap counts: PFR, 2013+
  - schedules (incl. playoffs): game results, and the league's draft ordering
  - draft picks: used only to settle exact ties when ordering teams by finish

Outputs to data/:
  player_season.parquet  one row per player-team-season: position group, cap $M, snap share, starter flag
  team_season.parquet    one row per team-season: cap $M and share by position group x role, plus results
                         (dead_m = base cap minus tracked cap hits: dead money plus unspent cap; can be slightly negative
                          when carryover lifts a team's cap above the base)
                         (orig_slot = pre-trade first-round slot in the next draft, 1 = worst finish ... 32 = champion;
                          finish = 33 - orig_slot, so 1 = best finish ... 32 = worst)
  qb_season.parquet      one row per passer-season: regular-season pass plays and total EPA
  qb_team_season.parquet same, split by team (a traded QB has one row per team)
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
# league-wide base salary cap by season, $M (before each team's carryover and adjustments)
BASE_CAP = {2013: 123.0, 2014: 133.0, 2015: 143.28, 2016: 155.27, 2017: 167.0, 2018: 177.2, 2019: 188.2,
            2020: 198.2, 2021: 182.5, 2022: 208.2, 2023: 224.8, 2024: 255.4, 2025: 279.2}
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
    """Per passer-team-season: regular-season pass plays (sacks included) and total EPA."""
    frames = []
    for season in range(FIRST, LAST + 1):
        d = nfl.load_pbp([season]).select(["season", "season_type", "play_type", "passer_player_id", "posteam", "epa"]).to_pandas()
        d = d[(d["season_type"] == "REG") & (d["play_type"] == "pass") & d["epa"].notna() & d["passer_player_id"].notna()]
        d["posteam"] = d["posteam"].replace(ABBR_FIX)
        frames.append(d.groupby(["passer_player_id", "season", "posteam"])["epa"].agg(pass_plays="size", epa_sum="sum").reset_index())
    return pd.concat(frames).rename(columns={"passer_player_id": "gsis_id", "posteam": "team"})


# PFR-style codes (draft file) and old franchise codes -> the current codes used everywhere else
DRAFT_CODE_FIX = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA", "LVR": "LV", "GNB": "GB", "KAN": "KC", "NOR": "NO",
                  "NWE": "NE", "SFO": "SF", "TAM": "TB", "SDG": "LAC"}
PLAYOFF_ROUND = {"WC": 1, "DIV": 2, "CON": 3, "SB": 4}


def original_draft_order(sched: pd.DataFrame, season: int) -> pd.DataFrame:
    """Each team's pre-trade first-round slot in the draft after `season` (1 = earliest pick = worst finish, 32 = champion).

    The league's rule: non-playoff teams by reverse regular-season record, then playoff teams grouped by the round they
    lost in (wild card, divisional, conference, Super Bowl loser), then the champion last. Within a group, worse record
    picks first; equal records are split by strength of schedule (LOWER strength of schedule picks first). Exact ties
    after that are returned in team order and settled by resolve_exact_ties().
    """
    g = sched[(sched["season"] == season) & sched["home_score"].notna()].copy()
    for c in ("home_team", "away_team"):
        g[c] = g[c].replace(DRAFT_CODE_FIX)
    rows = []
    for r in g[g["game_type"] == "REG"].itertuples():
        hw = 1.0 if r.home_score > r.away_score else 0.5 if r.home_score == r.away_score else 0.0
        rows += [(r.home_team, r.away_team, hw), (r.away_team, r.home_team, 1 - hw)]
    G = pd.DataFrame(rows, columns=["team", "opp", "w"])
    rec = G.groupby("team")["w"].agg(["sum", "count"])
    G["opp_w"], G["opp_n"] = G["opp"].map(rec["sum"]), G["opp"].map(rec["count"])
    sos = G.groupby("team").apply(lambda d: d["opp_w"].sum() / d["opp_n"].sum(), include_groups=False)
    group = {t: 0 for t in rec.index}                      # 0 = missed the playoffs
    for r in g[g["game_type"] != "REG"].itertuples():
        loser = r.home_team if r.home_score < r.away_score else r.away_team
        winner = r.away_team if loser == r.home_team else r.home_team
        group[loser] = max(group[loser], PLAYOFF_ROUND[r.game_type])
        if r.game_type == "SB":
            group[winner] = 5                              # champion
    df = pd.DataFrame({"team": rec.index, "pct": (rec["sum"] / rec["count"]).values,
                       "sos": sos.reindex(rec.index).values, "grp": [group[t] for t in rec.index]})
    df = df.sort_values(["grp", "pct", "sos", "team"]).reset_index(drop=True)
    df["slot"] = np.arange(1, len(df) + 1)
    df["season"] = season
    return df


def resolve_exact_ties(order: pd.DataFrame, actual_pick_by_slot: dict) -> pd.DataFrame:
    """Teams with identical group, record AND strength of schedule are ordered by rules/coin flips we cannot see.
    When the real draft shows those very teams holding exactly those slots, use the real order."""
    order = order.copy()
    for _, tied in order.groupby(["grp", "pct", "sos"]):
        if len(tied) < 2:
            continue
        slots = sorted(tied["slot"])
        held = [actual_pick_by_slot.get(s) for s in slots]
        if set(held) == set(tied["team"]):
            for team, slot in zip(held, slots):
                order.loc[order["team"] == team, "slot"] = slot
    return order.sort_values("slot").reset_index(drop=True)


def load_finish() -> pd.DataFrame:
    """Per team-season: orig_slot (pre-trade first-round slot in the next draft) and finish = 33 - orig_slot (1 = best)."""
    sched = nfl.load_schedules(list(range(FIRST, LAST + 1))).to_pandas()
    picks = nfl.load_draft_picks(list(range(FIRST + 1, LAST + 2))).to_pandas()
    picks = picks[picks["round"] == 1].copy()
    picks["team"] = picks["team"].replace(DRAFT_CODE_FIX)
    out = []
    for season in range(FIRST, LAST + 1):
        order = original_draft_order(sched, season)
        actual = picks[picks["season"] == season + 1]
        if len(actual) == 32:                              # forfeited first-rounders renumber the real draft; skip tie-breaking then
            order = resolve_exact_ties(order, dict(zip(actual["pick"], actual["team"])))
        out.append(order[["season", "team", "slot"]])
    f = pd.concat(out).rename(columns={"slot": "orig_slot"})
    f["finish"] = 33 - f["orig_slot"]
    return f


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
    # The contract data has no dead cap (a released player's remaining bonus is not in his season history), so
    # dead money is recovered as a residual: base cap minus tracked cap hits. It also holds any cap left unspent.
    wide["dead_m"] = wide["season"].map(BASE_CAP) - wide["tracked_cap_m"]

    qb1 = ps[(ps["pos_group"] == "QB") & (ps["role"] == "starter")] \
        .rename(columns={"rookie_deal": "qb1_rookie_deal", "draft_overall": "qb1_draft_overall", "cap_m": "qb1_cap_m"}) \
        [["season", "team", "qb1_rookie_deal", "qb1_draft_overall", "qb1_cap_m"]]
    wide = wide.merge(qb1, on=["season", "team"], how="left")

    ts = (wide.merge(results, on=["season", "team"], how="inner").merge(load_epa(), on=["season", "team"], how="left")
              .merge(load_finish(), on=["season", "team"], how="left"))
    ts.to_parquet(OUT / "team_season.parquet", index=False)
    qb_team = load_qb_passing()
    qb_team.to_parquet(OUT / "qb_team_season.parquet", index=False)
    qb_team.groupby(["gsis_id", "season"], as_index=False)[["pass_plays", "epa_sum"]].sum().to_parquet(OUT / "qb_season.parquet", index=False)

    print(f"player_season: {len(ps):,} rows | team_season: {len(ts)} rows "
          f"({ts.season.min()}-{ts.season.max()}, {ts.team.nunique()} teams)")
    print(f"cap rows with a snap match: {(ps.offense_snaps + ps.defense_snaps > 0).mean():.1%}")
    print(f"team-seasons with a QB1 identified: {ts.qb1_cap_m.notna().sum()} / {len(ts)}; "
          f"QB1 on rookie deal: {ts.qb1_rookie_deal.fillna(False).astype(bool).sum()}")


if __name__ == "__main__":
    main()
