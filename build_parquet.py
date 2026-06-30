"""
Build fantasy optimizer parquet.

Inputs:
  - betano_odds.json       : list of match dicts with odds + scorer odds
  - fifa_players_full.json : FIFA fantasy player data + round stats

Output:
  - fantasy_optimizer.parquet  : one row per player
  - fantasy_optimizer.csv      : same
  - match_log.txt              : fuzzy match log for QC
"""


from collections import defaultdict
import json, unicodedata, re
from rapidfuzz import process, fuzz
import pandas as pd



# ── Squad ID → English name mapping (1-indexed alphabetical order) ─────────────
SQUAD_ID_TO_EN = {
    1:  "Algeria",
    2:  "Argentina",
    3:  "Australia",
    4:  "Austria",
    5:  "Belgium",
    6:  "Bosnia and Herzegovina",
    7:  "Brazil",
    8:  "Cabo Verde",
    9:  "Canada",
    10: "Colombia",
    11: "Congo DR",
    12: "Cote d Ivoire",
    13: "Croatia",
    14: "Curacao",
    15: "Czechia",
    16: "Ecuador",
    17: "Egypt",
    18: "England",
    19: "France",
    20: "Germany",
    21: "Ghana",
    22: "Haiti",
    23: "IR Iran",
    24: "Iraq",
    25: "Japan",
    26: "Jordan",
    27: "Korea Republic",
    28: "Mexico",
    29: "Morocco",
    30: "Netherlands",
    31: "New Zealand",
    32: "Norway",
    33: "Panama",
    34: "Paraguay",
    35: "Portugal",
    36: "Qatar",
    37: "Saudi Arabia",
    38: "Scotland",
    39: "Senegal",
    40: "South Africa",
    41: "Spain",
    42: "Sweden",
    43: "Switzerland",
    44: "Tunisia",
    45: "Turkiye",
    46: "Uruguay",
    47: "USA",
    48: "Uzbekistan",
}

# Portuguese team name variants from Betano → canonical English name
# Built from known Betano PT names seen in the data
PT_TO_EN = {
    "paises baixos":     "Netherlands",
    "marrocos":          "Morocco",
    "costa do marfim":   "Cote d Ivoire",
    "noruega":           "Norway",
    "alemanha":          "Germany",
    "paraguai":          "Paraguay",
    "brasil":            "Brazil",
    "japao":             "Japan",
    "franca":            "France",
    "suecia":            "Sweden",
    "belgica":           "Belgium",
    "senegal":           "Senegal",
    "espanha":           "Spain",
    "austria":           "Austria",
    "portugal":          "Portugal",
    "croacia":           "Croatia",
    "africa do sul":     "South Africa",
    "canada":            "Canada",
    "mexico":            "Mexico",
    "equador":           "Ecuador",
    "inglaterra":        "England",
    "rd congo":          "Congo DR",
    "eua":               "USA",
    "bósnia-herzegovina": "Bosnia and Herzegovina",
    "colombia":          "Colombia",
    "uruguai":           "Uruguay",
    "argentina":         "Argentina",
    "jordania":          "Jordan",
    "argelia":           "Algeria",
    "coreia do sul":     "Korea Republic",
    "coreia":            "Korea Republic",
    "republica checa":   "Czechia",
    "tunisia":           "Tunisia",
    "suica":             "Switzerland",
    "arabia saudita":    "Saudi Arabia",
    "arabia saudi":      "Saudi Arabia",
    "cabo verde":        "Cabo Verde",
    "egito":             "Egypt",
    "ira":               "IR Iran",
    "irao":              "IR Iran",
    "nova zelandia":     "New Zealand",
    "panama":            "Panama",
    "gana":             "Ghana",
    "haiti":             "Haiti",
    "turquia":           "Turkiye",
    "curacao":           "Curacao",
    "catar":             "Qatar",
    "iraque":            "Iraq",
    "escócia":           "Scotland",
    "escocia":           "Scotland",
    "uzbequistao":       "Uzbekistan",
    "austrália":         "Australia",
    "australia":            "Australia",
    "australia":            "Australia",  # already have "austrália" but add plain too
    "australia":              "Australia",
    "bosnia-herzegovina":     "Bosnia and Herzegovina",
    "bosnia-herzegovina":     "Bosnia and Herzegovina",
    "bosnia-herzegovina":   "Bosnia and Herzegovina",
    "bosnia e herzegovina": "Bosnia and Herzegovina",
}

# ── Utility functions ─────────────────────────────────────────────────────────

def strip_accents(s: str) -> str:
    """Remove diacritics and normalize to ASCII."""
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")

def normalize(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    return re.sub(r"\s+", " ", strip_accents(s).lower().strip())

def pt_team_to_en(pt_name: str) -> str:
    """Convert Betano Portuguese team name to canonical English."""
    key = normalize(pt_name)
    if key in PT_TO_EN:
        return PT_TO_EN[key]
    # Fallback: return normalized as-is (will fail join but won't crash)
    return pt_name

def devig_pair(odd_yes: float, odd_no: float) -> float:
    """De-vig two-outcome market, return probability of 'yes'."""
    if not odd_yes or not odd_no:
        return None
    p_yes = 1 / odd_yes
    p_no = 1 / odd_no
    total = p_yes + p_no
    return round(p_yes / total, 4)

def implied_prob(odd: float) -> float:
    """Raw implied probability (with margin)."""
    if not odd or odd <= 1:
        return None
    return round(1 / odd, 4)

# ── Load inputs ───────────────────────────────────────────────────────────────

print("Loading betano_odds.json...")
with open("betano_odds.json", "r", encoding="utf-8") as f:
    betano_matches = json.load(f)

print("Loading fifa_players_full.json...")
with open("fifa_players_full.json", "r", encoding="utf-8") as f:
    fifa_data = json.load(f)

fifa_players = fifa_data["players"]
fifa_rounds   = fifa_data["rounds"]

# ── Build match-level signals from Betano ────────────────────────────────────
# Key: canonical English team name → dict of signals

team_signals = {}  # team_en -> signals dict

for match in betano_matches:
    home_pt = match["home"]
    away_pt = match["away"]
    home_en = pt_team_to_en(home_pt)
    away_en = pt_team_to_en(away_pt)

    def get_odd(lst, handicap=None, name_contains=None):
        for x in lst:
            if handicap is not None and abs(x.get("handicap", 999) - handicap) > 0.01:
                continue
            if name_contains and name_contains.lower() not in x.get("name", "").lower():
                continue
            return x.get("price")
        return None

    # 1X2
    odds_1x2 = match.get("1x2", [])
    home_win_odd = odds_1x2[0]["price"] if len(odds_1x2) > 0 else None
    draw_odd     = odds_1x2[1]["price"] if len(odds_1x2) > 1 else None
    away_win_odd = odds_1x2[2]["price"] if len(odds_1x2) > 2 else None

    # BTTS
    btts_list = match.get("btts", [])
    btts_yes_odd = get_odd(btts_list, name_contains="Sim")
    btts_no_odd  = get_odd(btts_list, name_contains="Não")
    btts_prob    = devig_pair(btts_yes_odd, btts_no_odd)

    # Total goals
    totals = match.get("totals", [])
    over_05_odd  = get_odd(totals, handicap=0.5, name_contains="Mais")
    over_15_odd  = get_odd(totals, handicap=1.5, name_contains="Mais")
    over_25_odd  = get_odd(totals, handicap=2.5, name_contains="Mais")
    over_35_odd  = get_odd(totals, handicap=3.5, name_contains="Mais")
    under_05_odd = get_odd(totals, handicap=0.5, name_contains="Menos")
    under_25_odd = get_odd(totals, handicap=2.5, name_contains="Menos")

    # Home team totals
    home_totals = match.get("home_totals", [])
    home_over_05_odd = get_odd(home_totals, handicap=0.5, name_contains="Mais")
    home_over_15_odd = get_odd(home_totals, handicap=1.5, name_contains="Mais")
    home_over_05_under_odd = get_odd(home_totals, handicap=0.5, name_contains="Menos")

    # Away team totals
    away_totals = match.get("away_totals", [])
    away_over_05_odd = get_odd(away_totals, handicap=0.5, name_contains="Mais")
    away_over_15_odd = get_odd(away_totals, handicap=1.5, name_contains="Mais")
    away_over_05_under_odd = get_odd(away_totals, handicap=0.5, name_contains="Menos")

    # Clean sheet probability: team keeps CS if opponent scores < 0.5
    # = devig of (opponent over 0.5 yes, opponent over 0.5 no)
    home_cs_prob = devig_pair(away_over_05_under_odd, away_over_05_odd)  # home CS = away doesn't score
    away_cs_prob = devig_pair(home_over_05_under_odd, home_over_05_odd)  # away CS = home doesn't score

    # Home expected goals proxy: implied prob of scoring over 0.5
    home_score_prob = devig_pair(home_over_05_odd, home_over_05_under_odd) if home_over_05_odd else None
    away_score_prob = devig_pair(away_over_05_odd, away_over_05_under_odd) if away_over_05_odd else None
    home_score_2_prob = implied_prob(home_over_15_odd)
    away_score_2_prob = implied_prob(away_over_15_odd)

    # Qualify / advance
    qualify = match.get("qualify", [])
    home_qualify_odd = qualify[0]["price"] if len(qualify) > 0 else None
    away_qualify_odd = qualify[1]["price"] if len(qualify) > 1 else None

    # Win by 2
    win_by_2 = match.get("win_by_2", [])
    home_win2_odd = win_by_2[0]["price"] if len(win_by_2) > 0 else None
    away_win2_odd = win_by_2[1]["price"] if len(win_by_2) > 1 else None

    # Over 2.5 match probability (de-vigged)
    over_25_prob = devig_pair(over_25_odd, under_25_odd)

    base_signals = {
        "match_home": home_en,
        "match_away": away_en,
        "match_home_win_odd":   home_win_odd,
        "match_draw_odd":       draw_odd,
        "match_away_win_odd":   away_win_odd,
        "match_btts_prob":      btts_prob,
        "match_over_05_odd":    over_05_odd,
        "match_over_15_odd":    over_15_odd,
        "match_over_25_odd":    over_25_odd,
        "match_over_25_prob":   over_25_prob,
        "match_over_35_odd":    over_35_odd,
        "match_qualify_home_odd": home_qualify_odd,
        "match_qualify_away_odd": away_qualify_odd,
        "match_win2_home_odd":  home_win2_odd,
        "match_win2_away_odd":  away_win2_odd,
    }

    home_signals = {
        **base_signals,
        "is_home": True,
        "opponent": away_en,
        "team_over_05_odd":   home_over_05_odd,
        "team_over_15_odd":   home_over_15_odd,
        "team_score_prob":    home_score_prob,
        "team_score_2_prob":  home_score_2_prob,
        "team_cs_prob":       home_cs_prob,
        "team_qualify_odd":   home_qualify_odd,
        "team_win2_odd":      home_win2_odd,
        "opp_over_05_odd":    away_over_05_odd,
        "opp_over_15_odd":    away_over_15_odd,
        "opp_score_prob":     away_score_prob,
        "opp_cs_prob":        away_cs_prob,
    }

    away_signals = {
        **base_signals,
        "is_home": False,
        "opponent": home_en,
        "team_over_05_odd":   away_over_05_odd,
        "team_over_15_odd":   away_over_15_odd,
        "team_score_prob":    away_score_prob,
        "team_score_2_prob":  away_score_2_prob,
        "team_cs_prob":       away_cs_prob,
        "team_qualify_odd":   away_qualify_odd,
        "team_win2_odd":      away_win2_odd,
        "opp_over_05_odd":    home_over_05_odd,
        "opp_over_15_odd":    home_over_15_odd,
        "opp_score_prob":     home_score_prob,
        "opp_cs_prob":        home_cs_prob,
    }

    team_signals[home_en] = home_signals
    team_signals[away_en] = away_signals

# ── Build scorer odds lookup: normalized player name → {anytime, first, last} ──

scorer_lookup = {}   # norm_name -> {anytime_odd, first_odd, last_odd, betano_team}

for match in betano_matches:
    scorers = match.get("scorers", {})
    home_en = pt_team_to_en(match["home"])
    away_en = pt_team_to_en(match["away"])

    for col, key in [("anytime", "anytime_odd"), ("first", "first_odd"), ("last", "last_odd")]:
        for entry in scorers.get(col, []):
            pname = entry.get("player", "")
            price = entry.get("price")
            team_pt = entry.get("team", "")
            team_en = pt_team_to_en(team_pt)
            norm = normalize(pname)
            if norm not in scorer_lookup:
                scorer_lookup[norm] = {
                    "betano_name": pname,
                    "betano_team": team_en,
                    "anytime_odd": None,
                    "first_odd":   None,
                    "last_odd":    None,
                }
            scorer_lookup[norm][key] = price

# All normalized Betano names for fuzzy matching
betano_names_norm = list(scorer_lookup.keys())

# ── Build FIFA player rows ────────────────────────────────────────────────────

match_log = []
rows = []

# Pre-build squad_id → canonical EN name using our mapping
def squad_to_en(squad_id):
    return SQUAD_ID_TO_EN.get(squad_id, f"Unknown_{squad_id}")

for p in fifa_players:
    squad_id = p.get("squad_id")
    team_en  = squad_to_en(squad_id)
    pos      = p.get("position")
    fifa_name = p.get("name", "")
    norm_fifa = normalize(fifa_name)

    # ── Match to team signals ────────────────────────────────────────────────
    signals = team_signals.get(team_en, {})


    

  # ── Fuzzy match to Betano scorer ─────────────────────────────────────────
    anytime_odd = None
    first_odd   = None
    last_odd    = None
    betano_match_name = None
    match_score = None

    FIFA_TO_BETANO = {
        "trincao":                "francisco trincao",
        "Martin degaard":        "Martin Odegaard",
        "martin degaard":         "Martin Odegaard",
        "martin odegaard":          "Odegaard",
        "martin odegaard":          "Ødegaard",
        "martin degaard":        "martin odegaard",
        "leo ostigard":           "leo skiri ostigard",
        "danilo dos santos":        "danilo dos santos",
        "rayan":                   "rayan vitor",
        "ibanez":                   "roger ibanez",
        "alejandro grimaldo":     "alex grimaldo",
        "pape matar sarr":        "pape sarr",
        "juan fernando quintero": "juan quintero",
        "abdul fatawu":             "abdul fatawu issahaku",
        "jose manuel lopez":      "flaco lopez",
        "matias fernandez-pardo": "matias fernandez pardo",
        "ahmed benbouali":        "nadhir benbouali",
        "paul okon":              "paul okon engstler",
        "prince adu":             "prince kwabena adu",
        "abdul baba":             "rahman baba",
        "cammy devlin":           "cammy devlin",
    }

    betano_key = FIFA_TO_BETANO.get(norm_fifa)
    if betano_key and betano_key in scorer_lookup:
        entry = scorer_lookup[betano_key]
        anytime_odd = entry["anytime_odd"]
        first_odd   = entry["first_odd"]
        last_odd    = entry["last_odd"]
        betano_match_name = entry["betano_name"]
        match_score = 100
        match_log.append(f"OVERRIDE  {fifa_name!r} -> {entry['betano_name']!r}")

    if anytime_odd is None and betano_names_norm:
        result = process.extractOne(
            norm_fifa,
            betano_names_norm,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=73,
        )
        if result:
            matched_norm, score, _ = result
            entry = scorer_lookup[matched_norm]
            if entry["betano_team"] == team_en or score >= 95:
                anytime_odd = entry["anytime_odd"]
                first_odd   = entry["first_odd"]
                last_odd    = entry["last_odd"]
                betano_match_name = entry["betano_name"]
                match_score = score
                match_log.append(f"MATCH  {fifa_name!r:40} -> {entry['betano_name']!r:40}  score={score}  team={team_en}")
            else:
                match_log.append(f"TEAM_MISMATCH  {fifa_name!r} matched {entry['betano_name']!r} score={score} but team {team_en} != {entry['betano_team']}")
        else:
            match_log.append(f"NO_MATCH  {fifa_name!r:40}  team={team_en}")

    # Default anytime odd if no match but player is in a team playing this round
    if anytime_odd is None and signals:
        anytime_odd = 150.0

    # ── Compute derived probability columns ──────────────────────────────────
    anytime_prob = round(1 / anytime_odd, 4) if anytime_odd and anytime_odd > 1 else None
    first_prob   = round(1 / first_odd, 4)   if first_odd   and first_odd   > 1 else None

    # ── Fantasy stats ────────────────────────────────────────────────────────
    stat_totals = defaultdict(float)
    matches_played = 0
    round_stats = p.get("round_stats") or []
    for r in round_stats:
        stats = r.get("stats") or {}
        if stats:
            matches_played += 1
        for k, v in stats.items():
            stat_totals[k] += v or 0

    round_points = p.get("round_points") or {}

    row = {
        # Identity
        "fifa_id":          p.get("id"),
        "name":             fifa_name,
        "squad_id":         squad_id,
        "team":             team_en,
        "position":         pos,
        "price":            p.get("price"),
        "status":           p.get("status"),

        # Fantasy performance
        "total_points":     p.get("total_points"),
        "avg_points":       p.get("avg_points"),
        "matches_played":   matches_played,
        "percent_selected": p.get("percent_selected"),
        "round_1_points":   round_points.get("1"),
        "round_2_points":   round_points.get("2"),
        "round_3_points":   round_points.get("3"),
        "round_4_points":   round_points.get("4"),
        "next_fixture":     p.get("next_fixture"),

        # Betano match
        "betano_matched_name": betano_match_name,
        "betano_match_score":  match_score,

        # Scorer odds
        "anytime_scorer_odd":  anytime_odd,
        "anytime_scorer_prob": anytime_prob,
        "first_scorer_odd":    first_odd,
        "first_scorer_prob":   first_prob,
        "last_scorer_odd":     last_odd,

        # Team match signals
        "match_home":            signals.get("match_home"),
        "match_away":            signals.get("match_away"),
        "is_home":               signals.get("is_home"),
        "opponent":              signals.get("opponent"),
        "match_home_win_odd":    signals.get("match_home_win_odd"),
        "match_draw_odd":        signals.get("match_draw_odd"),
        "match_away_win_odd":    signals.get("match_away_win_odd"),
        "match_btts_prob":       signals.get("match_btts_prob"),
        "match_over_25_odd":     signals.get("match_over_25_odd"),
        "match_over_25_prob":    signals.get("match_over_25_prob"),
        "match_over_35_odd":     signals.get("match_over_35_odd"),
        "team_over_05_odd":      signals.get("team_over_05_odd"),
        "team_over_15_odd":      signals.get("team_over_15_odd"),
        "team_score_prob":       signals.get("team_score_prob"),
        "team_score_2_prob":     signals.get("team_score_2_prob"),
        "team_cs_prob":          signals.get("team_cs_prob"),
        "team_qualify_odd":      signals.get("team_qualify_odd"),
        "team_win2_odd":         signals.get("team_win2_odd"),
        "opp_over_05_odd":       signals.get("opp_over_05_odd"),
        "opp_score_prob":        signals.get("opp_score_prob"),
        "opp_cs_prob":           signals.get("opp_cs_prob"),

        # Aggregate stats
        "stat_GS":  stat_totals.get("GS", 0),  # goals scored
        "stat_AS":  stat_totals.get("AS", 0),  # assists
        "stat_CS":  stat_totals.get("CS", 0),  # clean sheets
        "stat_GC":  stat_totals.get("GC", 0),  # goals conceded
        "stat_MP":  stat_totals.get("MP", 0),  # minutes played
        "stat_YC":  stat_totals.get("YC", 0),  # yellow cards
        "stat_RC":  stat_totals.get("RC", 0),  # red cards
        "stat_ST":  stat_totals.get("ST", 0),  # shots on target
        "stat_SB":  stat_totals.get("SB", 0),  # shots blocked
        "stat_CC":  stat_totals.get("CC", 0),  # chances created
        "stat_PS":  stat_totals.get("PS", 0),  # penalties saved
        "stat_T":   stat_totals.get("T", 0),   # tackles
        "stat_S":   stat_totals.get("S", 0),   # saves
        "stat_SXI": stat_totals.get("SXI", 0), # started XI
        "stat_OG":  stat_totals.get("OG", 0),  # own goals
        "stat_PC":  stat_totals.get("PC", 0),  # penalties committed
        "stat_PW":  stat_totals.get("PW", 0),  # penalties won
        "stat_FK":  stat_totals.get("FK", 0),  # free kicks
    }

    rows.append(row)

# ── Verify all Betano scorer names are matched ────────────────────────────────

matched_betano = set()
for p_row in rows:
    if p_row.get("betano_matched_name"):
        matched_betano.add(normalize(p_row["betano_matched_name"]))

unmatched_betano = []
for norm, entry in scorer_lookup.items():
    if norm not in matched_betano:
        unmatched_betano.append(entry["betano_name"])

if unmatched_betano:
    match_log.append(f"\n=== UNMATCHED BETANO PLAYERS ({len(unmatched_betano)}) ===")
    for n in sorted(unmatched_betano):
        match_log.append(f"  UNMATCHED_BETANO: {n}")

# ── Write match log ───────────────────────────────────────────────────────────
with open("match_log.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(match_log))
print(f"Match log written: {len(match_log)} lines")

# ── Build DataFrame and export ────────────────────────────────────────────────
df = pd.DataFrame(rows)

# Only keep players who have an upcoming match (have team signals)
df_playing = df[df["match_home"].notna()].copy()
df_all = df.copy()

print(f"\nTotal FIFA players:           {len(df_all)}")
print(f"Players with upcoming match:  {len(df_playing)}")
print(f"Players with Betano odds:     {df_playing['betano_matched_name'].notna().sum()}")
print(f"Unmatched Betano players:     {len(unmatched_betano)}")

df_playing.to_parquet("fantasy_optimizer.parquet", index=False)
df_playing.to_csv("fantasy_optimizer.csv", index=False)

print("\nSaved fantasy_optimizer.parquet and .csv")
print("\nSample (10 rows):")
print(df_playing[["name", "team", "position", "price", "anytime_scorer_odd",
                   "anytime_scorer_prob", "team_cs_prob", "team_score_prob"]].head(10).to_string())







# check fuzzy score to get cutoff
def normalize(s):
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.lower().strip())

with open("betano_odds.json") as f:
    betano = json.load(f)

targets = ["francisco trincao", "martin odegaard", "leo skiri ostigard",
           "alex grimaldo", "pape sarr", "juan quintero"]

all_names = []
for m in betano:
    for col in ["anytime", "first", "last"]:
        for e in m.get("scorers", {}).get(col, []):
            all_names.append(normalize(e["player"]))
all_names = list(set(all_names))

with open("fifa_players_full.json") as f:
    fifa = json.load(f)["players"]
fifa_names = {normalize(p["name"]): p["name"] for p in fifa}

for t in targets:
    r = process.extractOne(t, list(fifa_names.keys()), scorer=fuzz.token_sort_ratio)
    print(f"Betano '{t}' -> FIFA '{r}'")