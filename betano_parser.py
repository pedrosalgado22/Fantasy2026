import json
import time
import re
from curl_cffi import requests as cf

BASE      = "https://www.betano.pt"
COMP_API  = f"{BASE}/api/sport/futebol/competicoes/mundial/189813/"
MATCH_API = f"{BASE}/api/match-odds/{{slug}}/{{eid}}/"

HEADERS = {
    "accept":           "application/json, text/plain, */*",
    "accept-language":  "pt-PT,pt;q=0.9,en;q=0.8",
    "dnt":              "1",
    "sec-fetch-dest":   "empty",
    "sec-fetch-mode":   "cors",
    "sec-fetch-site":   "same-origin",
}

# ── PT name → canonical English ───────────────────────────────────────────────
# Translation happens HERE so betano_odds.json stores EN names.
# This prevents build_parquet.py's PT_TO_EN from being the single point of
# failure for teams with unusual Portuguese spellings (Bosnia, Ghana = "Gana").
PT_TO_EN = {
    "paises baixos":                  "Netherlands",
    "países baixos":                  "Netherlands",
    "marrocos":                       "Morocco",
    "costa do marfim":                "Cote d Ivoire",
    "noruega":                        "Norway",
    "alemanha":                       "Germany",
    "paraguai":                       "Paraguay",
    "brasil":                         "Brazil",
    "japao":                          "Japan",
    "japão":                          "Japan",
    "franca":                         "France",
    "frança":                         "France",
    "suecia":                         "Sweden",
    "suécia":                         "Sweden",
    "belgica":                        "Belgium",
    "bélgica":                        "Belgium",
    "senegal":                        "Senegal",
    "espanha":                        "Spain",
    "austria":                        "Austria",
    "áustria":                        "Austria",
    "portugal":                       "Portugal",
    "croacia":                        "Croatia",
    "croácia":                        "Croatia",
    "africa do sul":                  "South Africa",
    "áfrica do sul":                  "South Africa",
    "canada":                         "Canada",
    "canadá":                         "Canada",
    "mexico":                         "Mexico",
    "méxico":                         "Mexico",
    "equador":                        "Ecuador",
    "inglaterra":                     "England",
    "rd congo":                       "Congo DR",
    "república democrática do congo": "Congo DR",
    "eua":                            "USA",
    "bosnia-herzegovina":             "Bosnia and Herzegovina",
    "bósnia-herzegovina":             "Bosnia and Herzegovina",
    "bosna i hercegovina":            "Bosnia and Herzegovina",
    "bósnia e herzegovina":           "Bosnia and Herzegovina",
    "bosnia e herzegovina":           "Bosnia and Herzegovina",
    "colombia":                       "Colombia",
    "colômbia":                       "Colombia",
    "uruguai":                        "Uruguay",
    "argentina":                      "Argentina",
    "jordania":                       "Jordan",
    "jordânia":                       "Jordan",
    "argelia":                        "Algeria",
    "argélia":                        "Algeria",
    "coreia do sul":                  "Korea Republic",
    "republica checa":                "Czechia",
    "república checa":                "Czechia",
    "tunisia":                        "Tunisia",
    "tunísia":                        "Tunisia",
    "suica":                          "Switzerland",
    "suíça":                          "Switzerland",
    "arabia saudita":                 "Saudi Arabia",
    "arábia saudita":                 "Saudi Arabia",
    "cabo verde":                     "Cabo Verde",
    "egito":                          "Egypt",
    "irão":                           "IR Iran",
    "ira":                            "IR Iran",
    "nova zelandia":                  "New Zealand",
    "nova zelândia":                  "New Zealand",
    "panama":                         "Panama",
    "panamá":                         "Panama",
    "gana":                           "Ghana",       # 4 chars — critical for market matching
    "haiti":                          "Haiti",
    "turquia":                        "Turkiye",
    "turquía":                        "Turkiye",
    "curacao":                        "Curacao",
    "curaçao":                        "Curacao",
    "catar":                          "Qatar",
    "iraque":                         "Iraq",
    "escocia":                        "Scotland",
    "escócia":                        "Scotland",
    "uzbequistao":                    "Uzbekistan",
    "uzbequistão":                    "Uzbekistan",
    "australia":                      "Australia",
    "austrália":                      "Australia",
}


def pt_to_en(name: str) -> str:
    """Translate Betano PT team name to canonical EN. Returns original if unmapped."""
    result = PT_TO_EN.get(name.lower().strip())
    if result is None:
        print(f"  [!] PT_TO_EN MISSING: {name!r} — add it to PT_TO_EN")
        return name
    return result


# ── Session ───────────────────────────────────────────────────────────────────

def make_session():
    s = cf.Session()
    r = s.get(BASE + "/", impersonate="chrome120")
    print(f"Warmup: HTTP {r.status_code}")
    return s


# ── Match discovery ───────────────────────────────────────────────────────────

def get_matches(s):
    r = s.get(COMP_API, impersonate="chrome120", headers=HEADERS)
    print(f"Competition API: HTTP {r.status_code}")
    if r.status_code != 200:
        return []
    try:
        text = json.dumps(r.json())
    except Exception:
        text = r.text
    seen, out = set(), []
    for slug, eid in re.findall(r'/odds/([^/"]+)/(\d{7,10})/', text):
        if eid not in seen:
            seen.add(eid)
            out.append({"slug": slug, "eid": eid})
    print(f"Matches found: {len(out)}")
    return out


# ── Fetch popular tab ─────────────────────────────────────────────────────────

def fetch_popular(s, slug, eid):
    url = MATCH_API.format(slug=slug, eid=eid) + "?req=la,s,stnf,c,mb,mbl"
    r   = s.get(url, impersonate="chrome120", headers={
        **HEADERS, "referer": f"{BASE}/odds/{slug}/{eid}/"
    })
    if r.status_code != 200:
        return None
    try:
        data = r.json()
        if data.get("errors") or data.get("errorCode"):
            return None
        return data
    except Exception:
        return None


# ── Extract tableLayout selections ────────────────────────────────────────────

def extract_table_layout(market):
    tl = market.get("tableLayout")
    if not tl:
        return []
    col_title_list = [ct.get("title", "") for ct in tl.get("columnTitles", [])]
    groups         = {g.get("id"): g.get("title", "") for g in tl.get("groups", [])}
    results        = []
    for row in tl.get("rows", []):
        player_name = row.get("title", "")
        team_name   = groups.get(row.get("groupId", ""), "")
        no_group    = row.get("noGroup", False)
        for gs in row.get("groupSelections", []):
            for sel in gs.get("selections", []):
                col_idx   = sel.get("columnIndex", 0)
                col_title = col_title_list[col_idx] if col_idx < len(col_title_list) else ""
                results.append({
                    "player_name":  player_name if not no_group else None,
                    "team_name":    team_name,
                    "name":         sel.get("name", ""),
                    "price":        sel.get("price"),
                    "handicap":     sel.get("handicap"),
                    "column_index": col_idx,
                    "column_title": col_title,
                })
    return results


# ── Parse all markets ─────────────────────────────────────────────────────────

def parse_all_markets(raw):
    markets     = {}
    market_list = raw.get("data", {}).get("event", {}).get("markets", [])
    for mkt in market_list:
        name     = mkt.get("name", "")
        type_id  = mkt.get("typeId")
        std_sels = mkt.get("selections", [])
        tl_sels  = extract_table_layout(mkt)
        if std_sels:
            markets[name] = {
                "type":       "standard",
                "typeId":     type_id,
                "selections": [
                    {"name": s.get("name"), "price": s.get("price"),
                     "handicap": s.get("handicap")}
                    for s in std_sels
                ],
            }
        elif tl_sels:
            markets[name] = {"type": "tableLayout", "typeId": type_id,
                             "selections": tl_sels}
    return markets


# ── Build clean output ────────────────────────────────────────────────────────

def build_clean(home_en: str, away_en: str, markets: dict,
                home_pt: str, away_pt: str) -> dict:
    out = {
        "home":        home_en,
        "away":        away_en,
        "1x2":         [],
        "btts":        [],
        "totals":      [],
        "home_totals": [],
        "away_totals": [],
        "win_by_2":    [],
        "qualify":     [],
        "handicap":    [],
        "scorers":     {"anytime": [], "first": [], "last": []},
    }

    home_l = home_pt.lower()   # PT name — matches Betano market strings
    away_l = away_pt.lower()

    for name, mkt in markets.items():
        nl   = name.lower()
        sels = mkt["selections"]
        t    = mkt["type"]

        if t == "standard":
            rows = [{"name": s["name"], "price": s["price"], "handicap": s["handicap"]}
                    for s in sels]

            if "resultado final" in nl:
                out["1x2"] = rows

            elif "ambas as equipas marcam" in nl and "ou" not in nl:
                out["btts"] = rows

            elif nl == "total de golos mais/menos":
                # Exact match → match-level total (no team prefix in market name)
                out["totals"] = rows

            elif ("total de golos mais/menos" in nl and
                  any(home_l[:n] in nl
                      for n in [8, 7, 6, 5, 4, 3]   # FIX 1: 4 and 3 added
                      if len(home_l) >= n)):
                out["home_totals"] = rows

            elif ("total de golos mais/menos" in nl and
                  any(away_l[:n] in nl
                      for n in [8, 7, 6, 5, 4, 3]   # FIX 1: 4 and 3 added
                      if len(away_l) >= n)):
                out["away_totals"] = rows

            elif "+2 golos vantagem" in nl or "2 golos de vantagem" in nl:
                out["win_by_2"] = rows

            elif "qualificar" in nl:
                out["qualify"] = rows

        elif t == "tableLayout":
            if "handicap" in nl:
                lines: dict = {}
                for s in sels:
                    h = s.get("handicap")
                    lines.setdefault(h, []).append(
                        {"name": s["name"], "price": s["price"]}
                    )
                out["handicap"] = [
                    {"line": h, "selections": v}
                    for h, v in sorted(
                        lines.items(),
                        key=lambda x: (x[0] is None, x[0] or 0)
                    )
                ]

            elif "marcar em qualquer altura" in nl or "marcador" in nl:
                for s in sels:
                    if s.get("player_name") is None:
                        continue
                    entry = {
                        "player": s["player_name"],
                        "team":   s["team_name"],
                        "name":   s["name"],
                        "price":  s["price"],
                    }
                    col       = s.get("column_index", 0)
                    col_title = s.get("column_title", "").lower()
                    if col == 0 or any(k in col_title for k in ("qualquer", "anytime")):
                        out["scorers"]["anytime"].append(entry)
                    elif col == 1 or any(k in col_title for k in ("primeiro", "first")):
                        out["scorers"]["first"].append(entry)
                    elif col == 2 or any(k in col_title for k in ("último", "last")):
                        out["scorers"]["last"].append(entry)

    for key in ("anytime", "first", "last"):
        out["scorers"][key].sort(key=lambda x: x["price"] or 999)

    return out


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    s = make_session()

    matches = get_matches(s)
    if not matches:
        print("Auto-discovery failed — using fallback")
        matches = [{"slug": "paises-baixos-marrocos", "eid": "88049190"}]

    all_results = []

    for i, m in enumerate(matches):
        slug, eid = m["slug"], m["eid"]
        print(f"\n[{i+1}/{len(matches)}] {slug}")

        raw = fetch_popular(s, slug, eid)
        if not raw:
            print("  FAILED")
            continue

        event   = raw.get("data", {}).get("event", {})
        name    = event.get("shortName", slug)
        parts   = name.split(" - ", 1)
        home_pt = parts[0].strip()
        away_pt = parts[1].strip() if len(parts) > 1 else ""
        home_en = pt_to_en(home_pt)
        away_en = pt_to_en(away_pt)

        markets = parse_all_markets(raw)
        clean   = build_clean(home_en, away_en, markets, home_pt, away_pt)
        all_results.append(clean)

        print(f"  {home_pt!r} → {home_en!r}  vs  {away_pt!r} → {away_en!r}")
        print(f"  1x2:         {[(x['name'], x['price']) for x in clean['1x2']]}")
        print(f"  btts:        {[(x['name'], x['price']) for x in clean['btts']]}")
        t25 = [x for x in clean['totals'] if x.get('handicap') == 2.5]
        print(f"  total >2.5:  {[(x['name'], x['price']) for x in t25]}")
        h05 = [x for x in clean['home_totals'] if x.get('handicap') == 0.5]
        a05 = [x for x in clean['away_totals'] if x.get('handicap') == 0.5]
        print(f"  home >0.5:   {[(x['name'], x['price']) for x in h05]}")
        print(f"  away >0.5:   {[(x['name'], x['price']) for x in a05]}")
        print(f"  win_by_2:    {[(x['name'], x['price']) for x in clean['win_by_2']]}")
        print(f"  handicap:    {[x['line'] for x in clean['handicap']]}")
        print(f"  scorers ({len(clean['scorers']['anytime'])}): "
              f"{[(x['player'], x['price']) for x in clean['scorers']['anytime'][:5]]}")

        # Diagnostic: warn immediately on empty team totals so name mismatches
        # are caught at fetch time rather than discovered as NaN in the parquet.
        if not clean["home_totals"]:
            print(f"  [!] home_totals EMPTY — market matching failed for PT name: {home_pt!r}")
            total_mkt_names = [k for k in markets if "total" in k.lower()]
            print(f"      Total markets available: {total_mkt_names}")
        if not clean["away_totals"]:
            print(f"  [!] away_totals EMPTY — market matching failed for PT name: {away_pt!r}")
            total_mkt_names = [k for k in markets if "total" in k.lower()]
            print(f"      Total markets available: {total_mkt_names}")

        time.sleep(1.0)

    with open("betano_odds.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(all_results)}/{len(matches)} saved to betano_odds.json")
