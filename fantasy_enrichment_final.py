import re
import unicodedata
import pandas as pd

FANTASY_CSV = "fantasy_optimizer.csv"
STATS_CSV = "top5_leagues_stats.csv"
OUT_CSV = "fantasy_enriched.csv"

MAX_EDIT_DIST = 1

# ── Load and filter ───────────────────────────────────────────────────────────

fantasy = pd.read_csv(FANTASY_CSV)
print(f"Total players: {len(fantasy)}")
print(fantasy["status"].value_counts().to_string())

fantasy = fantasy[fantasy["status"] != "transferred"].reset_index(drop=True)
print(f"\nAfter removing transferred: {len(fantasy)}")
print(fantasy.groupby("team")["name"].count().sort_values(ascending=False).to_string())

stats = pd.read_csv(STATS_CSV)
print(f"\nStats rows: {len(stats)}")

# ── Helpers ───────────────────────────────────────────────────────────────────

def norm(s):
    if pd.isna(s):
        return ""
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", re.sub(r"\s+", " ", s)).strip()

def lev(a, b):
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[-1] + 1, prev[j-1] + (ca != cb)))
        prev = curr
    return prev[-1]

def best_match(name, pool):
    fn = norm(name)
    best_dist, best_idx = MAX_EDIT_DIST + 1, None
    for idx, cn in zip(pool.index, pool["_name_norm"]):
        if abs(len(cn) - len(fn)) > MAX_EDIT_DIST:
            continue
        d = lev(fn, cn)
        if d < best_dist:
            best_dist, best_idx = d, idx
    if best_idx is not None and best_dist <= MAX_EDIT_DIST:
        return best_idx, best_dist
    return None, None

# ── Aggregate stats ───────────────────────────────────────────────────────────

stats["fbref_code"] = stats["Nation"].str.extract(r"([A-Z]{2,4})$")

COUNT_COLS = [c for c in [
    "MP", "Starts", "Min", "90s",
    "Gls", "Ast", "G+A", "xG", "xAG", "npxG", "G-PK",
    "Tkl", "TklW", "Blocks", "Int", "Tkl+Int", "Clr", "Err",
    "PrgP", "PrgC", "KP", "PPA", "xA", "Ast_stats_passing",
    "GA", "Saves", "CS", "PKA", "PKsv",
    "Touches", "Carries", "PrgR", "Mis", "Dis",
    "CrdY", "CrdR", "PKwon", "PKcon", "Recov",
    "PK", "PKatt", "SoTA", "PKm", "Sh", "SoT",
    "Fls", "Fld", "Off", "Crs", "OG", "2CrdY",
] if c in stats.columns]

RATE_COLS = [c for c in [
    "Cmp%_stats_passing", "Save%", "CS%",
    "GA90", "SoT%", "Sh/90", "SoT/90", "G/Sh", "G/SoT",
] if c in stats.columns]

META_COLS = [c for c in ["Pos", "Squad", "Comp", "Age"] if c in stats.columns]

agg_dict = {c: "sum" for c in COUNT_COLS}
agg_dict.update({c: "first" for c in RATE_COLS})
agg_dict.update({c: "first" for c in META_COLS})
if "Squad" in META_COLS:
    agg_dict["Squad"] = lambda x: " / ".join(x.dropna().astype(str).unique())

stats_agg = stats.groupby(["Player", "fbref_code"], as_index=False, sort=False).agg(agg_dict)
stats_agg["fbref_multi_club"] = stats.groupby(["Player", "fbref_code"]).size().reset_index(name="n")["n"].gt(1).values
stats_agg["_name_norm"] = stats_agg["Player"].apply(norm)

print(f"Stats aggregated: {len(stats_agg)} players")

# ── Nation map ────────────────────────────────────────────────────────────────

NATION_MAP = {
    "Algeria": "ALG", "Argentina": "ARG", "Australia": "AUS", "Austria": "AUT",
    "Belgium": "BEL", "Bosnia and Herzegovina": "BIH", "Brazil": "BRA",
    "Cabo Verde": "CPV", "Canada": "CAN", "Colombia": "COL", "Congo DR": "COD",
    "Croatia": "CRO", "Curacao": "CUW", "Czechia": "CZE", "Ecuador": "ECU",
    "Egypt": "EGY", "England": "ENG", "France": "FRA", "Germany": "GER",
    "Ghana": "GHA", "Haiti": "HAI", "IR Iran": "IRN", "Iraq": "IRQ",
    "Japan": "JPN", "Jordan": "JOR", "Korea Republic": "KOR", "Mexico": "MEX",
    "Morocco": "MAR", "Netherlands": "NED", "New Zealand": "NZL", "Norway": "NOR",
    "Panama": "PAN", "Paraguay": "PAR", "Portugal": "POR", "Qatar": "QAT",
    "Saudi Arabia": "KSA", "Scotland": "SCO", "Senegal": "SEN",
    "South Africa": "RSA", "Spain": "ESP", "Sweden": "SWE", "Switzerland": "SUI",
    "Tunisia": "TUN", "Turkiye": "TUR", "Uruguay": "URU", "USA": "USA",
    "Uzbekistan": "UZB", "Cote d Ivoire": "CIV",
}

fantasy["fbref_code"] = fantasy["team"].map(NATION_MAP)

unmapped = fantasy.loc[fantasy["fbref_code"].isna(), "team"].dropna().unique()
if len(unmapped):
    print(f"\nUNMAPPED TEAMS: {list(unmapped)}")
else:
    print("\n✓ All teams mapped")

# ── Filter stats to tournament nations ───────────────────────────────────────

codes = set(fantasy["fbref_code"].dropna().unique())
stats_filtered = stats_agg[stats_agg["fbref_code"].isin(codes)].copy()
print(f"Stats rows for tournament nations: {len(stats_filtered)}")

print("\nCoverage per nation (fantasy squad | fbref players):")
for code in sorted(codes):
    n_fantasy = (fantasy["fbref_code"] == code).sum()
    n_stats = (stats_filtered["fbref_code"] == code).sum()
    print(f"  {code}: {n_fantasy:>2} fantasy  |  {n_stats:>3} in fbref")

# ── Merge ─────────────────────────────────────────────────────────────────────

ADD_COLS = COUNT_COLS + RATE_COLS + META_COLS + ["fbref_multi_club"]
for col in ADD_COLS:
    fantasy[f"fbref_{col}"] = pd.NA
fantasy["fbref_matched_player"] = pd.NA
fantasy["fbref_match_dist"] = pd.NA

match_log = []

for code, grp in fantasy.groupby("fbref_code", dropna=True):
    pool = stats_filtered[stats_filtered["fbref_code"] == code]
    if pool.empty:
        continue
    for idx in grp.index:
        fname = fantasy.at[idx, "name"]
        match_idx, dist = best_match(fname, pool)
        if match_idx is None:
            continue
        row = stats_filtered.loc[match_idx]
        for col in ADD_COLS:
            if col in row.index:
                fantasy.at[idx, f"fbref_{col}"] = row[col]
        fantasy.at[idx, "fbref_matched_player"] = row["Player"]
        fantasy.at[idx, "fbref_match_dist"] = dist
        match_log.append({"nation": code, "fantasy": fname, "fbref": row["Player"], "dist": dist})

# ── Report ────────────────────────────────────────────────────────────────────

matched = fantasy["fbref_match_dist"].notna().sum()
print(f"\nMatched {matched} / {len(fantasy)} ({matched/len(fantasy):.1%})")

match_df = pd.DataFrame(match_log)
if not match_df.empty:
    print(f"  dist=0: {(match_df['dist']==0).sum()}")
    print(f"  dist=1: {(match_df['dist']==1).sum()}")

    suspect = match_df[match_df["dist"] == 1].sort_values("nation")
    if not suspect.empty:
        print(f"\nDist=1 matches (verify):")
        print(suspect[["nation","fantasy","fbref"]].to_string(index=False))

print(f"\nMatch rate by nation:")
for code, grp in fantasy.groupby("fbref_code", dropna=True):
    n_matched = grp["fbref_match_dist"].notna().sum()
    n_total = len(grp)
    flag = "  <- no top-5 data" if n_matched == 0 else ""
    print(f"  {code}: {n_matched}/{n_total} ({n_matched/n_total:.0%}){flag}")

unmatched = fantasy[fantasy["fbref_match_dist"].isna()][["name","team","position"]]
print(f"\nUnmatched by position:")
print(unmatched["position"].value_counts().to_string())

# ── Save ──────────────────────────────────────────────────────────────────────

fantasy = fantasy.drop(columns=["fbref_code"], errors="ignore")
fantasy.to_csv(OUT_CSV, index=False)
print(f"\nSaved {OUT_CSV} — {fantasy.shape[0]} rows x {fantasy.shape[1]} cols")
