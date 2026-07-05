# Fantasy2026 — FIFA World Cup 2026 Fantasy Optimizer

![Status](https://img.shields.io/badge/stage-Round%20of%2016-blue)

A personal probabilistic optimization system for the FIFA World Cup 2026 official fantasy game. The pipeline scrapes live bookmaker odds and FIFA fantasy data, converts odds into de-vigged probabilities, models expected fantasy points per player per FIFA's scoring rules, and solves for the budget-optimal 15-man squad (and 11-man starting XI) via mixed-integer linear programming.

This README documents the pipeline **as of the Round of 16** (8 matches, 16 teams). It will be extended as later rounds are played and modeled.

---

## Research Question

*Given the confirmed Round of 16 fixtures, which 15-player squad — under budget, formation and max-4-players-per-nation constraints — maximizes total expected fantasy points, and who should be captained?*

---

## Repository Contents

| File | Role |
|---|---|
| `fifa_fantasy_data.py` | Scrapes `play.fifa.com/json/fantasy` (`players.json`, `rounds.json`, per-player `player_stats/{id}.json`) → `fifa_players_full.json` |
| `betano_parser.py` | Scrapes Betano (`curl_cffi`) for the round's matches; parses 1X2, BTTS, totals, team totals, qualification, handicap and scorer (anytime/first/last) markets → `betano_odds.json` |
| `build_parquet.py` | Joins FIFA players to Betano match/team signals (team-name PT→EN mapping, squad-ID→nation mapping) and to Betano scorer odds (fuzzy name matching) → `fantasy_optimizer.parquet` / `.csv` |
| `players_data-2025_2026.csv`, `players_data_light-2025_2026.csv` | FBref top-5-league club stats, evaluated as a tertiary signal |
| `final_data_merging.ipynb` | Joins club stats (Levenshtein-matched), derives implied/de-vigged probabilities from odds, engineers form/rate/ranking features |
| `preprocess.ipynb` | Orchestrates the full run: executes the three scraping/build scripts, then `final_data_merging.ipynb`, handles missing data, drops unusable columns, normalizes → `fantasy_enriched.csv` |
| `fantasy_enrichment_final.py` | Expected-points model: sigmoid/Poisson probability functions per FIFA point source |
| `algorithm.ipynb` / `algorithmr16.html` | Aggregates expected points, runs the squad optimizer (PuLP/CBC) and the transfer optimizer for the Round of 16 window |
| `fantasy_optimizer.csv` / `.parquet` | Base joined dataset, pre-feature-engineering |
| `fantasy_enriched.csv` | Final feature set consumed by the optimizer |
| `match_log.txt` | Diagnostic log of every Betano↔FIFA player name match (fuzzy score, overrides, unmatched) |
| `betano_odds.json` | Raw parsed Betano output for the round's 8 matches |
| `fifa_players_full.json` | Raw FIFA fantasy player + round-by-round stats |

---

## Data Sources

| Source | Used for |
|---|---|
| **FIFA Fantasy API** (`play.fifa.com/json/fantasy`) | Player identity, position, price, status, cumulative + round-by-round stats, fantasy points history |
| **Betano** (scraped via `curl_cffi`, PT locale) | Match odds — primary signal. 1X2, BTTS, over/under (match, home, away), qualification, handicap, and anytime/first/last scorer markets |
| **FBref** (top-5 European leagues) | Club-level stats — tertiary signal only |

**Signal hierarchy (by design):** Betano odds dominate; tournament stats are secondary; club stats are tertiary — because a meaningful share of the player pool doesn't play in the top-5 leagues Betano/FBref cover well.

---

## Methodology

**1. Data collection.** FIFA fantasy data and Betano odds are scraped independently per round. Betano's competition page is scanned for match slugs/event IDs; each match's popular-odds tab is fetched and parsed into standard and table-layout (scorer) markets.

**2. Name & team matching.**
- Team names: Betano's Portuguese team names are mapped to canonical English via a manual `PT_TO_EN` dict; FIFA's numeric `squad_id` is mapped 1–48 to nations in alphabetical English order.
- Player names: accent-stripped, lowercased, then fuzzy-matched (`rapidfuzz`, `token_sort_ratio`, cutoff 73) against Betano scorer-market names, gated by team match unless the score is ≥95. A manual `FIFA_TO_BETANO` override dict resolves known problem cases (e.g. `Ødegaard` vs `Odegaard`/diacritics, `Trincão`, `Grimaldo` vs `Alejandro Grimaldo`).
- Players with no scorer-market entry default to an anytime-scorer odd of **150.0** (≈0.67% implied) rather than being left null.

**3. Probability construction from odds.** Two-outcome markets (BTTS, over/under) are de-vigged (`p = (1/odd_yes) / (1/odd_yes + 1/odd_no)`); one-sided markets use raw implied probability (`1/odd`). Clean-sheet probability is derived from the *opponent's* under-0.5-goals market rather than a direct clean-sheet line.

**4. Feature engineering.** Round-by-round FIFA stats are turned into per-90 rates, recent-form windows (last 3/5), streaks, and — critically — **percentile ranks within team × position** (price, minutes, starts, selection %, scorer odds, shots, chances created, tackles). Stratifying by team and position prevents attacking players from dominating rankings purely on raw scoring odds when compared against defenders/goalkeepers.

**5. Expected-points model.** Every FIFA scoring source gets its own probability/expectation estimate, combined with position- and event-appropriate math:

| Event type | Method used | Why |
|---|---|---|
| Binary, single-occurrence (plays at all, plays 60+, red card, penalty conceded, own goal) | Sigmoid over a weighted feature blend | Correct for events that either happen once or don't |
| Expected-count events (goals, assists, tackles, shots on target, chances created, saves, goals conceded) | Poisson λ (`λ = -ln(1 - p)`), since `E[Poisson(λ)] = λ`, so bonus points = `λ / threshold` | Wrong to sigmoid-compress something whose *expected count*, not just occurrence, matters |
| Goals conceded penalty (GK/DEF) | Full Poisson PMF (`P(0),P(1),P(2),P(3),4+)` over λ, expectation `-(λ − 1 + e^-λ)` | Captures FIFA's "no deduction for first goal conceded" rule exactly |
| Scouting bonus (+2 if <5% selected and >4 base points) | Poisson 90% CI on total base expected points vs. threshold 4 | Approximates P(exceeds 4) without a hard threshold cutoff |

FIFA's underlying point values used throughout:

| Source | GK | DEF | MID | FWD | All positions |
|---|---|---|---|---|---|
| Appearance (<60 / 60+ min) | — | — | — | — | +1 / +1 |
| Goal | +9 | +7 | +6 | +5 | — |
| Clean sheet (60+ min) | +5 | +5 | +1 | 0 | — |
| Every 3 saves | +1 | — | — | — | — |
| Penalty save | +3 | — | — | — | — |
| Every 3 tackles | — | — | +1 | — | — |
| Every 2 big chances created | — | — | +1 | — | — |
| Every 2 shots on target | — | — | — | +1 | — |
| Assist | — | — | — | — | +3 |
| Yellow / Red card | — | — | — | — | −1 / −2 |
| Own goal | — | — | — | — | −2 |
| Penalty won / conceded | — | — | — | — | +2 / −1 |
| Direct free-kick goal (bonus) | — | — | — | — | +1 |
| Scouting bonus (<5% selected, >4 base pts) | — | — | — | — | +2 |

**6. Squad optimization (PuLP / CBC, MILP).**
- Squad: 15 players, exactly 2 GK / 5 DEF / 5 MID / 3 FWD, ≤4 per nation, budget ≤ **$105.0M**.
- Starting XI: 11 players, exactly 1 GK, 3–5 DEF, 3–5 MID, 1–3 FWD.
- Objective: maximize `Σ EP(starting XI) + Σ EP(captain, doubled) + 0.6 × Σ EP(bench)`.
- A separate **no-budget "ideal XI"** run (same formation/nation rules, 11 players only) is solved as a benchmark for how much the budget cap costs in expected points.
- A **transfer-optimization** variant takes a person's current 15-man squad, treats players no longer in the player pool as forced-out, and maximizes net expected points minus a −3 penalty per transfer beyond the free-transfer allowance.

---

## Dataset Size Through the Pipeline (Round of 16 run)

| Stage | Rows | Columns | Note |
|---|---|---|---|
| Raw FIFA player pool | 1,489 | — | All registered fantasy players |
| Joined to Betano signals (`build_parquet.py`) | 534 | 134 | Players whose nation has one of the 8 R16 fixtures; 355 also had a matched scorer odd (2 Betano scorers unmatched) |
| + FBref, missing-value handling, feature engineering, normalized (`fantasy_enriched.csv`) | 416 | 195 | Filtered to `status == "playing"`; club-stat columns dropped (43.75–95.2% missing — most players play outside the top-5 leagues covered by FBref); `next_fixture` and `team_win2_odd` dropped (100% missing — the "+2 goals" market returned no selections in any of the 8 matches this round) |
| + per-point-source expected-value columns (feeds the optimizer) | ~414 | ~250 | `e_appearance`, `e_goal`, `e_assist`, `e_cs`, `e_gc`, `e_saves`, `e_pen_save`, `e_tackles`, `e_cc`, `e_sot`, `e_yc`, `e_rc`, `e_og`, `e_pw`, `e_pc`, `e_quali`, `e_scouting` → summed into `expected_points` |

---

## Key Findings — Round of 16 Optimal Squad

**Budget-constrained optimum:** Expected points **127.73**, cost **$105.0M** (full budget used).

| Pos | Player | Nation | Price | EP | |
|---|---|---|---|---|---|
| GK | Emiliano Martínez | Argentina | $5.0M | 8.19 | |
| DEF | Achraf Hakimi | Morocco | $6.0M | 7.74 | |
| DEF | Lisandro Martínez | Argentina | $4.6M | 7.17 | |
| DEF | Nahuel Molina | Argentina | $4.4M | 6.93 | scouting differential |
| MID | Ousmane Dembélé | France | $10.0M | 9.60 | |
| MID | Michael Olise | France | $9.5M | 9.37 | |
| MID | Vinícius Júnior | Brazil | $10.0M | 8.95 | |
| MID | Ismael Saibari | Morocco | $6.8M | 7.77 | |
| FWD | **Kylian Mbappé** | France | $10.5M | 12.77 | **captain** |
| FWD | Lionel Messi | Argentina | $10.0M | 11.78 | |
| FWD | Mikel Oyarzabal | Spain | $8.1M | 8.22 | |

**Bench:** Mike Maignan (GK, France, EP 7.20) · Dávinson Sánchez (DEF, Colombia, EP 6.63) · Noussair Mazraoui (DEF, Morocco, EP 6.13) · Brahim Díaz (MID, Morocco, EP 7.48)

**Nation breakdown:** Argentina 4, France 4, Morocco 4, Brazil 1, Colombia 1, Spain 1 (all ≤ the 4-per-nation cap).

**No-budget "ideal XI" benchmark:** EP 111.92 — same core (Martínez, Hakimi, L. Martínez, Molina, Dembélé, Olise, Vinícius, Mbappé-C, Messi, Oyarzabal) but swaps Saibari for Bradley Barcola (France, not affordable/selectable in the budget run because of the 4-per-nation cap, not price). *Note: the two objective values aren't directly comparable — the budget-squad figure includes the 0.6-weighted bench, the ideal-XI figure doesn't.*

**Transfer-optimization example run:** starting from a sample prior 15-man squad with one player no longer eligible, the model found an all-free (4 transfers, no penalty) upgrade path — OUT: Pickford, Dest, Kane, Musiala (eliminated) / IN: Olise, Oyarzabal, Martínez, Hakimi — raising the squad to EP 122.07 at $104.4M.

---

## Key Learnings, Fixes & Known Limitations

- **Odds > tournament stats > club stats**, by design and by necessity — club-level data covers only ~56% of the R16 player pool.
- **Sigmoid is for binary events only.** Early iterations sigmoided everything; expected-count events (goals, tackles, shots, saves, chances created) now use Poisson λ, since a sigmoid compresses magnitude information that a rate-based event needs.
- **Team × position percentile ranking** normalizes across squads of very different depth — but has a known failure mode: a squad with only one viable option at a position (e.g. a lone recognized forward on the bench of an otherwise defensive-minded nation) can rank #1 in every team-relative signal on thin sample size alone, inflating a low-quality player above better options elsewhere. Not yet corrected; flagged for the next iteration.
- **Caught bug:** goalkeeper goal-probability wasn't zeroed in `prob_scores` before it fed `expected_points`, which pushed Emiliano Martínez above Mike Maignan on a nonsensical "chance to score" component rather than genuinely superior clean-sheet/save value. Fixed by explicitly zeroing `prob_scores` for `GK`.
- **Caught bug:** Portuguese team-name substring matching against Betano market strings failed for names under 5 characters (`"Gana"` = Ghana, 4 chars). Fixed by extending the matched substring-length range down to 4 and 3 characters.
- **Fallback convention:** any player on a team with a confirmed fixture but no individual Betano scorer entry gets anytime-odd = 150.0 rather than a null, so downstream probability math never breaks on missing scorer coverage.

---

## Tech Stack

| Tool | Purpose |
|---|---|
| Python 3 | Core pipeline and modeling language |
| `curl_cffi` | Browser-impersonating HTTP client for Betano scraping |
| `rapidfuzz` | Fuzzy player-name matching (`token_sort_ratio`) |
| `pandas` / `numpy` | Data wrangling, feature engineering |
| `pyarrow` (parquet) | Columnar storage of the base joined dataset |
| `scikit-learn` | `MinMaxScaler` for feature/price normalization |
| `scipy.stats` | `poisson`, `norm` for count-event and scouting-bonus probability |
| `PuLP` (CBC solver) | Mixed-integer squad and transfer optimization |
| Jupyter Notebook | Pipeline orchestration and iteration |

---

## Status

Round of 16 squad selection is complete for the pre-kickoff odds snapshot documented above. **To be continued:**
- Round of 16 realized results vs. modeled expected points (model validation).
- Quarterfinal odds re-scrape and re-optimization.
- Fix for the thin-position-depth ranking bias noted above.
- Extending club-stat coverage or formally down-weighting it further given persistent sparsity.

---

*Personal project — FIFA World Cup 2026 official fantasy game.*
