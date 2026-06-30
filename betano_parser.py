import json
import time
import re
from curl_cffi import requests as cf

BASE     = "https://www.betano.pt"
COMP_API = f"{BASE}/api/sport/futebol/competicoes/mundial/189813/"
MATCH_API = f"{BASE}/api/match-odds/{{slug}}/{{eid}}/"

HEADERS = {
    "accept":           "application/json, text/plain, */*",
    "accept-language":  "pt-PT,pt;q=0.9,en;q=0.8",
    "dnt":              "1",
    "sec-fetch-dest":   "empty",
    "sec-fetch-mode":   "cors",
    "sec-fetch-site":   "same-origin",
}

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
    referer = f"{BASE}/odds/{slug}/{eid}/"
    r = s.get(url, impersonate="chrome120", headers={**HEADERS, "referer": referer})
    if r.status_code != 200:
        return None
    try:
        data = r.json()
        if data.get("errors") or data.get("errorCode"):
            return None
        return data
    except Exception:
        return None

# ── Extract selections from tableLayout ──────────────────────────────────────

def extract_table_layout(market):
    """
    Handle markets with tableLayout (scorers, handicap).
    Returns list of {name, price, handicap, column_index, column_title, group_title, player_name}
    """
    tl = market.get("tableLayout")
    if not tl:
        return []

    # Map columnIndex -> column title (anytime/first/last for scorers)
    col_titles = {}
    for ct in tl.get("columnTitles", []):
        col_titles[ct.get("typeId")] = ct.get("title", "")

    # Map groupId -> team name
    groups = {}
    for g in tl.get("groups", []):
        groups[g.get("id")] = g.get("title", "")

    results = []
    col_title_list = [ct.get("title", "") for ct in tl.get("columnTitles", [])]

    for row in tl.get("rows", []):
        player_name = row.get("title", "")
        group_id = row.get("groupId", "")
        team_name = groups.get(group_id, "")
        no_group = row.get("noGroup", False)

        for gs in row.get("groupSelections", []):
            for sel in gs.get("selections", []):
                col_idx = sel.get("columnIndex", 0)
                col_title = col_title_list[col_idx] if col_idx < len(col_title_list) else ""
                results.append({
                    "player_name": player_name if not no_group else None,
                    "team_name": team_name,
                    "name": sel.get("name", ""),
                    "price": sel.get("price"),
                    "handicap": sel.get("handicap"),
                    "column_index": col_idx,
                    "column_title": col_title,
                })
    return results

# ── Parse all markets from raw response ──────────────────────────────────────

def parse_all_markets(raw):
    """
    Parse data.event.markets list — handles both:
    - Standard markets: selections[] array
    - TableLayout markets: tableLayout.rows[].groupSelections[].selections[]
    Returns dict keyed by market name.
    """
    markets = {}
    event = raw.get("data", {}).get("event", {})
    market_list = event.get("markets", [])

    for mkt in market_list:
        name = mkt.get("name", "")
        type_id = mkt.get("typeId")

        # Standard selections
        std_sels = mkt.get("selections", [])

        # TableLayout selections
        tl_sels = extract_table_layout(mkt)

        if std_sels:
            markets[name] = {
                "type": "standard",
                "typeId": type_id,
                "selections": [
                    {"name": s.get("name"), "price": s.get("price"), "handicap": s.get("handicap")}
                    for s in std_sels
                ]
            }
        elif tl_sels:
            markets[name] = {
                "type": "tableLayout",
                "typeId": type_id,
                "selections": tl_sels
            }

    return markets

# ── Build clean output ────────────────────────────────────────────────────────

def build_clean(home, away, markets):
    out = {
        "home": home,
        "away": away,
        "1x2": [],
        "btts": [],
        "totals": [],
        "home_totals": [],
        "away_totals": [],
        "win_by_2": [],
        "qualify": [],
        "handicap": [],
        "scorers": {
            "anytime": [],
            "first": [],
            "last": [],
        },
    }

    home_l = home.lower()
    away_l = away.lower()

    for name, mkt in markets.items():
        nl = name.lower()
        sels = mkt["selections"]
        t = mkt["type"]

        if t == "standard":
            rows = [{"name": s["name"], "price": s["price"], "handicap": s["handicap"]} for s in sels]

            if "resultado final" in nl:
                out["1x2"] = rows

            elif "ambas as equipas marcam" in nl and "ou" not in nl:
                out["btts"] = rows

            elif "total de golos mais/menos" == nl:
                out["totals"] = rows

            elif "total de golos mais/menos" in nl and any(
                home_l[:n] in nl for n in [8, 7, 6, 5] if len(home_l) >= n
            ):
                out["home_totals"] = rows

            elif "total de golos mais/menos" in nl and any(
                away_l[:n] in nl for n in [8, 7, 6, 5] if len(away_l) >= n
            ):
                out["away_totals"] = rows

            elif "+2 golos vantagem" in nl or "2 golos de vantagem" in nl:
                out["win_by_2"] = rows

            elif "qualificar" in nl:
                out["qualify"] = rows

        elif t == "tableLayout":
            if "handicap" in nl:
                # Flatten handicap rows grouped by handicap line
                lines = {}
                for s in sels:
                    h = s.get("handicap")
                    if h not in lines:
                        lines[h] = []
                    lines[h].append({"name": s["name"], "price": s["price"]})
                out["handicap"] = [{"line": h, "selections": v} for h, v in sorted(lines.items())]

            elif "marcar em qualquer altura" in nl or "marcador" in nl:
                for s in sels:
                    if s.get("player_name") is None:
                        continue
                    entry = {
                        "player": s["player_name"],
                        "team": s["team_name"],
                        "name": s["name"],
                        "price": s["price"],
                    }
                    col = s.get("column_index", 0)
                    col_title = s.get("column_title", "").lower()
                    if col == 0 or "qualquer" in col_title or "anytime" in col_title or "qualquer altura" in col_title:
                        out["scorers"]["anytime"].append(entry)
                    elif col == 1 or "primeiro" in col_title or "first" in col_title:
                        out["scorers"]["first"].append(entry)
                    elif col == 2 or "último" in col_title or "last" in col_title:
                        out["scorers"]["last"].append(entry)

    # Sort anytime scorers by price ascending (most likely first)
    out["scorers"]["anytime"].sort(key=lambda x: x["price"] or 999)
    out["scorers"]["first"].sort(key=lambda x: x["price"] or 999)
    out["scorers"]["last"].sort(key=lambda x: x["price"] or 999)

    return out

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    s = make_session()

    matches = get_matches(s)
    if not matches:
        print("Auto-discovery failed")
        matches = [{"slug": "paises-baixos-marrocos", "eid": "88049190"}]

    all_results = []

    for i, m in enumerate(matches):
        slug, eid = m["slug"], m["eid"]
        print(f"\n[{i+1}/{len(matches)}] {slug}")

        raw = fetch_popular(s, slug, eid)
        if not raw:
            print("  FAILED")
            continue

        event = raw.get("data", {}).get("event", {})
        name = event.get("shortName", slug)
        parts = name.split(" - ", 1)
        home = parts[0].strip()
        away = parts[1].strip() if len(parts) > 1 else ""

        markets = parse_all_markets(raw)
        clean = build_clean(home, away, markets)
        all_results.append(clean)

        print(f"  {home} vs {away}")
        print(f"  1x2:        {[(x['name'], x['price']) for x in clean['1x2']]}")
        print(f"  btts:       {[(x['name'], x['price']) for x in clean['btts']]}")
        t25 = [x for x in clean['totals'] if x.get('handicap') == 2.5]
        print(f"  total 2.5:  {[(x['name'], x['price']) for x in t25]}")
        h05 = [x for x in clean['home_totals'] if x.get('handicap') == 0.5]
        a05 = [x for x in clean['away_totals'] if x.get('handicap') == 0.5]
        print(f"  home >0.5:  {[(x['name'], x['price']) for x in h05]}")
        print(f"  away >0.5:  {[(x['name'], x['price']) for x in a05]}")
        print(f"  win_by_2:   {[(x['name'], x['price']) for x in clean['win_by_2']]}")
        print(f"  handicap lines: {[x['line'] for x in clean['handicap']]}")
        print(f"  anytime scorers ({len(clean['scorers']['anytime'])}): "
              f"{[(x['player'], x['price']) for x in clean['scorers']['anytime'][:5]]}")

        time.sleep(1.0)

    with open("betano_odds.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(all_results)}/{len(matches)} saved to betano_odds.json")
