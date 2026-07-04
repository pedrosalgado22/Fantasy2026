import numpy as np
import pandas as pd
from scipy.stats import poisson
from pulp import *




# ── Scouting bonus expected value ─────────────────────────────────────────────
# Rule: +2 if player scores >4 BASE points AND is in <5% of teams.
# Ownership is known pre-round. The >4pt threshold requires a probability
# estimate: model points as Poisson(mu=expected_points) — standard in soccer
# fantasy literature. E[scouting] = I(ownership<5%) * P(X>4|mu) * 2.

def add_scouting_ep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["scouting_eligible"] = (df["percent_selected"] < 5.0).astype(float)
    df["prob_exceeds_4pts"] = df["expected_points"].apply(
        lambda mu: float(1 - poisson.cdf(4, max(mu, 1e-9)))
    )
    df["ep_scouting"] = df["scouting_eligible"] * df["prob_exceeds_4pts"] * 2
    return df


# ── ILP Optimizer ─────────────────────────────────────────────────────────────

def optimize_squad(
    df: pd.DataFrame,
    budget: float = 100.0,        # $100M group stage | $105M knockout
    max_per_country: int = 3,     # 3 group/R32 | 4 R16 | 5 QF | 6 SF | 8 F
    vc_dnp_prob: float = 0.10,    # P(captain DNP): approximation for VC bonus
    bench_weight: float = 0.05,   # discount factor for bench auto-sub value
    solver=None,
) -> dict | None:
    """
    Integer linear programme solving the FIFA WC Fantasy 2026 squad selection.

    Decision variables
    ─────────────────
    x[i] ∈ {0,1}  player i in 15-man squad
    s[i] ∈ {0,1}  player i in starting XI          (implies x[i]=1)
    b[i] ∈ {0,1}  player i on bench                (x[i] = s[i] + b[i])
    c[i] ∈ {0,1}  player i is captain              (must be in XI)
    v[i] ∈ {0,1}  player i is vice-captain         (must be in XI, ≠ captain)

    Objective (all in expected-points space)
    ──────────────────────────────────────
    max  Σ ep[i]·s[i]                              # XI base
       + Σ ep[i]·c[i]                              # captain doubling extra
       + Σ ep[i]·vc_dnp_prob·v[i]                 # VC expected extra (approx)
       + Σ ep_scouting[i]·s[i]                    # scouting bonus
       + Σ ep[i]·bench_weight·b[i]                # bench auto-sub upside
    """
    if "ep_scouting" not in df.columns:
        df = add_scouting_ep(df)

    idx = df.index.tolist()

    # ── Decision variables ────────────────────────────────────────────────────
    x = LpVariable.dicts("squad", idx, cat="Binary")
    s = LpVariable.dicts("xi",    idx, cat="Binary")
    b = LpVariable.dicts("bench", idx, cat="Binary")
    c = LpVariable.dicts("cap",   idx, cat="Binary")
    v = LpVariable.dicts("vc",    idx, cat="Binary")

    model = LpProblem("FIFA_WC_Fantasy_2026", LpMaximize)

    # ── Objective ─────────────────────────────────────────────────────────────
    model += lpSum(
        df.loc[i, "expected_points"]                          * s[i]
        + df.loc[i, "expected_points"]                        * c[i]
        + df.loc[i, "expected_points"] * vc_dnp_prob          * v[i]
        + df.loc[i, "ep_scouting"]                            * s[i]
        + df.loc[i, "expected_points"] * bench_weight          * b[i]
        for i in idx
    )

    # ── Squad size ────────────────────────────────────────────────────────────
    model += lpSum(x[i] for i in idx) == 15
    model += lpSum(s[i] for i in idx) == 11
    model += lpSum(b[i] for i in idx) == 4

    for i in idx:
        model += s[i] + b[i] == x[i]   # partition: every squad player is XI or bench

    # ── Budget ────────────────────────────────────────────────────────────────
    model += lpSum(df.loc[i, "price"] * x[i] for i in idx) <= budget

    # ── Squad position composition (15-man) ───────────────────────────────────
    for pos, count in [("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]:
        p_idx = df[df["position"] == pos].index.tolist()
        model += lpSum(x[i] for i in p_idx) == count

    # ── Country limit ─────────────────────────────────────────────────────────
    for country in df["team"].unique():
        c_idx = df[df["team"] == country].index.tolist()
        if c_idx:
            model += lpSum(x[i] for i in c_idx) <= max_per_country

    # ── Starting XI: goalkeeper ───────────────────────────────────────────────
    gk_idx = df[df["position"] == "GK"].index.tolist()
    model += lpSum(s[i] for i in gk_idx) == 1    # exactly 1 GK starts
    model += lpSum(b[i] for i in gk_idx) == 1    # exactly 1 GK on bench

    # ── Starting XI: valid outfield formation ─────────────────────────────────
    # The 7 permitted formations are: 4-4-2, 4-3-3, 4-5-1, 3-4-3,
    # 3-5-2, 5-4-1, 5-3-2. All satisfy:
    #   DEF ∈ [3,5], MID ∈ [3,5], FWD ∈ [1,3], DEF+MID+FWD = 10 (implicit).
    # These bounds are tight — no invalid combination passes both constraints.
    for pos, lo, hi in [("DEF", 3, 5), ("MID", 3, 5), ("FWD", 1, 3)]:
        p_idx = df[df["position"] == pos].index.tolist()
        model += lpSum(s[i] for i in p_idx) >= lo
        model += lpSum(s[i] for i in p_idx) <= hi

    # ── Captain ───────────────────────────────────────────────────────────────
    model += lpSum(c[i] for i in idx) == 1
    for i in idx:
        model += c[i] <= s[i]       # captain must be in XI

    # ── Vice-captain ──────────────────────────────────────────────────────────
    model += lpSum(v[i] for i in idx) == 1
    for i in idx:
        model += v[i] <= s[i]       # VC must be in XI
        model += c[i] + v[i] <= 1  # captain ≠ vice-captain

    # ── Solve ─────────────────────────────────────────────────────────────────
    solver = solver or PULP_CBC_CMD(msg=0)
    model.solve(solver)

    if LpStatus[model.status] != "Optimal":
        print(f"[!] Solver status: {LpStatus[model.status]}")
        return None

    # ── Extract solution ──────────────────────────────────────────────────────
    in_squad = [i for i in idx if value(x[i]) > 0.5]
    in_xi    = [i for i in idx if value(s[i]) > 0.5]
    on_bench = [i for i in idx if value(b[i]) > 0.5]
    captain  = next(i for i in idx if value(c[i]) > 0.5)
    vc       = next(i for i in idx if value(v[i]) > 0.5)

    return {
        "squad":    df.loc[in_squad].copy(),
        "xi":       df.loc[in_xi].copy(),
        "bench":    df.loc[on_bench].copy(),
        "captain":  captain,
        "vc":       vc,
        "total_ep": value(model.objective),
        "cost":     df.loc[in_squad, "price"].sum(),
        "status":   LpStatus[model.status],
    }


# ── Display ───────────────────────────────────────────────────────────────────

POS_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}

def print_solution(result: dict, show_bench: bool = True) -> None:
    if result is None:
        print("No solution found.")
        return

    xi    = result["xi"].copy()
    bench = result["bench"].copy()
    cap   = result["captain"]
    vc    = result["vc"]

    xi["_ord"]    = xi["position"].map(POS_ORDER)
    bench["_ord"] = bench["position"].map(POS_ORDER)
    xi    = xi.sort_values(["_ord", "expected_points"], ascending=[True, False])
    bench = bench.sort_values(["_ord", "expected_points"], ascending=[True, False])

    def row_str(i, row):
        tag   = " [C]" if i == cap else " [V]" if i == vc else ""
        scout = " ★SCOUT" if row.get("scouting_eligible", 0) > 0.5 else ""
        return (f"  {row['position']:3}  {row['name']:<28} {row['team']:<22}"
                f"${row['price']:.1f}  EP:{row['expected_points']:.2f}{tag}{scout}")

    w = 72
    print(f"\n{'═'*w}")
    print(f"  EXPECTED POINTS: {result['total_ep']:.2f}   COST: ${result['cost']:.1f}M")
    print(f"{'═'*w}")

    print(f"\n  STARTING XI")
    print(f"  {'─'*68}")
    for i, row in xi.iterrows():
        print(row_str(i, row))

    if show_bench:
        print(f"\n  BENCH  (auto-sub priority: 1 → 4)")
        print(f"  {'─'*68}")
        for rank, (i, row) in enumerate(bench.iterrows(), 1):
            print(f"  [{rank}]" + row_str(i, row)[4:])

    print(f"\n  Country breakdown:")
    counts = result["squad"]["team"].value_counts()
    for team, n in counts.items():
        print(f"    {team}: {n}")
    print(f"{'═'*w}\n")


# ── Usage ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df = pd.read_parquet("fantasy_optimizer.parquet")
    df = df[df["status"] == "playing"].copy()

    # expected_points must exist before add_scouting_ep
    # If it's not in the parquet, compute it here:
    EP_COLS = [c for c in df.columns if c.startswith("ep_") and c != "ep_scouting"]
    assert EP_COLS, f"No ep_ columns found. Run the EP computation cells first. Columns: {df.columns.tolist()}"
    df["expected_points"] = df[EP_COLS].sum(axis=1)

    df = add_scouting_ep(df)
    result = optimize_squad(df, budget=105.0, max_per_country=4)
    print_solution(result)

    # Round of 16 (budget +5M, country limit +1)
    # result = optimize_squad(df, budget=105.0, max_per_country=4)
