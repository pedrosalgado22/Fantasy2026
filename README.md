# World Cup 2026 Fantasy Optimizer

A probabilistic squad selection system built for FIFA's official World Cup 2026 fantasy game. The system combines bookmaker odds with FIFA fantasy platform data to compute expected fantasy points per player, then selects a valid squad using integer linear programming.

This project began during the Round of 16 after a 6th place standing as of that point.

## Repository Contents

1. `fifa_fantasy_data.py`. Retrieves player data, prices, positions, and round by round statistics from the FIFA fantasy API. Outputs `fifa_players_full.json`.
2. `fifa_players_full.json`. Raw output of `fifa_fantasy_data.py`.
3. `betano_parser.py`. Retrieves and parses Betano odds for match winner, both teams to score, totals, team totals, qualification, and scorer markets. Outputs `betano_odds.json`.
4. `betano_odds.json`. Raw output of `betano_parser.py`.
5. `build_parquet.py`. Merges odds data with FIFA fantasy data. Player names are matched between sources using fuzzy string matching. Outputs `fantasy_optimizer.parquet`, `fantasy_optimizer.csv`, and `match_log.txt`.
6. `fantasy_optimizer.parquet`, `fantasy_optimizer.csv`. Merged dataset produced by `build_parquet.py`.
7. `match_log.txt`. Log of matched and unmatched player names produced during the fuzzy matching step in `build_parquet.py`.
8. `players_data-2025_2026.csv`, `players_data_light-2025_2026.csv`. Club level statistics exports from FBref, full and reduced versions. Associated with the discontinued club stats phase of the project.
9. `final_data_merging.ipynb`. Joins club level statistics to the merged FIFA and Betano dataset using edit distance name matching. Associated with the discontinued club stats phase.
10. `preprocess.ipynb`. Handles missing values and computes model input features, including per ninety minute rates and team and position stratified ranks. Outputs `fantasy_enriched.csv`.
11. `fantasy_enriched.csv`. Feature engineered dataset produced by `preprocess.ipynb`, consumed by `algorithm.ipynb`.
12. `algorithm.ipynb`. Contains the expected points model, the squad optimizer, and the transfer optimizer. Re executed each round.
13. `algorithm2.html`, `algorithm4.html`, `algorithm8.html`, `algorithm16.html`. Static exports of `algorithm.ipynb`, preserved as a record of the model at the final, semi final, quarter final, and round of 16 stages respectively.
14. `README.md`. This document.

## Data Sources

Two active data sources are used. Betano, for match and player odds, retrieved through its public API and the FIFA fantasy platform, for player prices, positions, point totals, and round by round statistics.

A third source, club level statistics from FBref, was used during early development and later discontinued.

## Impossibility to deploy a fully automated system

Deploying a fully automated model would have taken more time, which was a constraint during the development of this algorithm (during Round of 32 for Round of 16). Not only that, but the needed database for such a project would need to very specific and treated carefully due to the "bubble" the World Cup represents in the context of competitive football.

1. International friendlies and qualfiers might not reflect competitive tactics or full strength lineups.
2. Club level statistics reflect a different context of teammates, tactical systems, and opposition quality, and might not transfer reliably to international competition.
3. The only prior World Cup dataset is four years old and reflects a substantially different player pool in different form.

Such a limitation is the reason the projects is standing on bookies' shoulders, which will have a much more capable predicative model regardless and add a degree of an automation to the algorithm.

## Reliance on Bookmaker Odds

Bookmaker odds incorporate information, including squad news and internal tactical intelligence not available to this project. An independently constructed probability estimate was unlikely to outperform odds derived probabilities under these conditions. Betano odds were therefore treated as the primary signal for point sources such as goal scoring and clean sheet probability.

## Club Level Statistics, Discontinued

FBref statistics were joined to FIFA player records using name matching with an edit distance tolerance of two characters. This source was discontinued for two reasons. More than half of the player pool competes outside the top five European leagues covered by FBref, resulting in low coverage. Club level performance also does not transfer reliably to international competition, due to differing teammates, tactical systems, and opposition quality. The final model relies on Betano odds, in tournament statistics, and manually assigned coefficients.

## Methodology

### Probability Estimation

Implied probability is calculated as one divided by the decimal odd. Two way markets are de vigged by dividing each side's implied probability by the sum of both sides, removing bookmaker margin.

### Event Modeling

Single occurrence events, including red cards, conceded penalties, and own goals, are modeled using a sigmoid function applied to a weighted combination of input signals.

Countable, repeatable events, including goals, assists, saves, tackles, shots on target, and chances created, are modeled as Poisson processes. A rate parameter is recovered from an estimated occurrence probability using the relationship that the probability of zero occurrences equals the negative exponential of the rate. Solving for the rate gives the natural log of one minus the probability, negated. Since the expected value of a Poisson variable equals its rate, threshold based bonus points are computed as rate divided by threshold, without further transformation.

### Ranking

Player price, minutes played, starts, selection percentage, and scoring odds are converted to percentile ranks within team and position groups. This prevents distortion between positions, since forward players score more frequently than defenders by default.

### Missing Data Handling

Players with a confirmed fixture but no matched Betano scorer market entry were assigned a default anytime scorer odd of 150, treating them as extreme long shots rather than leaving the value undefined. Round by round statistical columns with no recorded value, resulting from a player not participating in that round, were filled with zero, to keep aggregate and rolling statistics computable across the full player pool.

### Expected Points Calculation

Expected value is computed per scoring category. Goals are valued at 9 points for goalkeepers, 7 for defenders, 6 for midfielders, and 5 for forwards. Clean sheets are valued at 5 points for goalkeepers and defenders, 1 for midfielders, and 0 for forwards. Additional categories include appearance points, assists, a goals conceded penalty for goalkeepers and defenders, save and penalty save bonuses for goalkeepers, tackle and chance creation bonuses for midfielders, shots on target bonuses for forwards, card and own goal penalties, penalty win and concede adjustments, and a qualification bonus scaled by team advancement probability.

A differential, or scouting, bonus applies if a player is selected by fewer than 5 percent of managers and exceeds 4 base points in a match. This is modeled using a 90 percent Poisson confidence interval around expected base points. The full bonus is awarded if the lower bound exceeds 4 points. No bonus is awarded if the upper bound is below 4 points. If the interval spans 4 points, the bonus is scaled by the tail probability of exceeding 4 points given the expected value.

An elimination risk adjustment, introduced after the round of 16, subtracts an amount equal to 1.5 multiplied by the probability of the player's team not qualifying, applied after the differential bonus is calculated. This adjustment is additive rather than proportional, so it does not disproportionately reduce the expected points of high output players.

An attacking output penalty for goalkeepers and defenders, also introduced after the round of 16, reduces expected points from goal contributions for these positions. This addressed a pattern in which selections were inflated by low probability, high variance attacking outcomes, combined with the higher per goal point value assigned to these positions relative to midfielders and forwards.

### Squad Selection

Squad selection is formulated as an integer linear program and solved using the CBC solver. The objective maximizes total expected points across an 11 player starting lineup, with captain points doubled and bench player points weighted at 0.6. Constraints include a budget of $105.0M, a 15 player squad composed of 2 goalkeepers, 5 defenders, 5 midfielders, and 3 forwards, a legal starting formation of 1 goalkeeper, 3 to 5 defenders, 3 to 5 midfielders, and 1 to 3 forwards, and a maximum of 4 players per nation. A maximum of 2 combined goalkeepers and defenders per nation was added after the round of 16, described in Model Evolution below.

### Transfer Optimization

A separate formulation evaluates transfers from an existing squad. Each transfer beyond a fixed free transfer allowance is penalized by 3 points in the objective function. Forced transfers, required when a player becomes ineligible, are excluded from this penalty.

## Round Summaries

### Round of 16

Transfers. Out: Jordan Pickford, Sergiño Dest, Harry Kane, Jamal Musiala. In: Michael Olise, Mikel Oyarzabal, Emiliano Martínez, Achraf Hakimi.

A model error was identified in this round. Goal scoring probability for goalkeepers was not set to zero prior to squad selection, contributing to Emiliano Martínez being selected over Mike Maignan.

Result: 102 points, the highest recorded score in the private league for this round.

<img width="806" height="636" alt="image" src="https://github.com/user-attachments/assets/fdb6199e-5077-418e-8d37-590c99bccb5b" />

### Quarter Finals

Transfers. Out: Vinícius Júnior, Christian Pulisic, Camilo Vargas, Johan Manzambi. In: Brahim Díaz, Unai Simón, Jude Bellingham, Dani Olmo.

Result: 82 points, second place in the private league. Non booster teams on the wider leaderboard scored between 85 and 90 points in this round.

<img width="779" height="711" alt="image" src="https://github.com/user-attachments/assets/c8e4ba5f-defe-4e65-9a39-db22609f1624" />

### Semi Finals

Transfers. Out: Unai Simón, Facundo Medina, Emiliano Martínez, Brahim Díaz, Achraf Hakimi. In: Mike Maignan, Jordan Pickford, Nahuel Molina, Anthony Gordon, Lucas Digne.

The final selection deviated from 2 of the 5 transfers suggested by the model, Anthony Gordon was selected in place of Adrien Rabiot, and Nahuel Molina in place of Cristian Romero. This followed an assessment that the model was undervaluing goal and assist probability in midfield selection relative to clean sheet and appearance probability.

Result: 56 points, third place in the private league. Non booster teams on the wider leaderboard scored between 60 and 80 points in this round. This is the lowest recorded result of the tournament, attributed to zero goals scored by an odds favored French attacking line across the match.

<img width="820" height="684" alt="image" src="https://github.com/user-attachments/assets/5314cf14-8889-4adb-bbb1-add52083d021" />

### Final

The model recommended squad, listed below, was not used. A squad weighted toward Spain was selected instead, in order to increase the probability of overtaking the private league leader rather than to maximize expected points.

Model recommended squad, expected points 81.98, cost $105.0M:

* GK Mike Maignan (France) $5.0M, 3.10 EP
* DEF Marc Cucurella (Spain) $5.1M, 3.36 EP
* DEF Lisandro Martínez (Argentina) $4.6M, 3.24 EP
* DEF Cristian Romero (Argentina) $4.9M, 3.22 EP
* DEF Jules Koundé (France) $5.4M, 3.18 EP
* DEF Nico O'Reilly (England) $4.7M, 2.83 EP
* MID Jude Bellingham (England) $8.3M, 6.93 EP
* MID Michael Olise (France) $9.5M, 6.87 EP
* MID Ousmane Dembélé (France) $10.0M, 6.57 EP
* MID Dani Olmo (Spain) $7.7M, 4.57 EP [SCOUT]
* MID Adrien Rabiot (France) $6.4M, 3.76 EP
* FWD Lionel Messi (Argentina) $10.0M, 9.19 EP [C]
* FWD Kylian Mbappé (France) $10.5M, 8.91 EP
* FWD Mikel Oyarzabal (Spain) $8.1M, 5.30 EP
* GK Jordan Pickford (England) $4.8M, 3.02 EP

Result: consistent with the round average, in the range of 75 to 80 points.

## Results

Round of 32 standing: 6th place, 377 points. Final standing: 2nd place, 670 points.

Deviations from model recommendations in the semi final and final rounds preceded improved relative outcomes compared to full adherence to model output in earlier rounds. This supports characterizing the system as a decision support tool rather than an autonomous selector.

Selection accuracy and predictive separation decreased in later rounds. This is attributed to a narrowing player pool and reduced performance variance among the remaining, higher quality teams.

## Model Evolution

After the round of 16, three changes were made. An attacking output penalty was applied to goalkeepers and defenders. A maximum of 2 combined goalkeepers and defenders per nation was added to reduce concentration risk in a single team's defense. Betano weighting for goal scoring and clean sheet probability was reduced by approximately 10 percentage points in favor of tournament derived data.

After the semi final, scoring and assist coefficients were increased. This followed an observed pattern in which the model favored players with higher clean sheet or appearance probability over players with comparable or higher scoring and assist probability, reducing the model's ability to identify high ceiling outcomes.

Additional coefficient adjustments were made across rounds without a corresponding written entry in this document. By the final round, the maximum players per nation constraint had been raised from 4 to 6, the bench weight had been raised from 0.6 to 0.9, and the elimination risk penalty had been reduced in magnitude from 1.5 to 1.0 points. The qualification bonus term was also set to zero for the final round, since no further tournament advancement remained to reward. These changes reflect continuous, informal recalibration between rounds rather than a single fixed model version deployed throughout the tournament.

## Known Limitations

1. Team name resolution relies on hardcoded string matching and manually maintained Portuguese to English dictionaries. A different bookmaker, tournament, or team naming convention would require manual reconfiguration.
2. No abstraction layer separates data source specific logic from the remainder of the pipeline.
3. Model weights and thresholds were assigned manually based on football domain knowledge, not fitted from data.
4. Reliance on a single bookmaker introduces exposure to that bookmaker's individual pricing errors. During the round of 16, Betano assigned Erling Haaland lower goal scoring probability than several less prolific forwards, including Julián Álvarez and a benched Romelu Lukaku.
5. The model was not deployed from the start of the tournament. Full operation began at the round of 16, reducing the number of rounds available for calibration and excluding the group stage and round of 32 from live testing.
6. Predictive separation decreased as the tournament progressed, consistent with a narrowing player pool and reduced variance among remaining teams.
7. Bench player point outcomes are not predictable within this framework, since playing time allocation is a coaching decision made after the squad selection deadline.
8. Player availability was patched manually in code ahead of each round, based on externally sourced injury and squad news, since the FIFA fantasy API status field did not reliably reflect real world unavailability in time for the selection deadline.
9. A small squad ranking bias was identified and not fully resolved. Team and position stratified ranking can assign a top rank to a player with limited playing time, if that player is the only one with meaningful minutes at their position for a given nation, inflating their apparent standing relative to their actual quality.
10. Automated notebook execution through nbconvert was unreliable in at least one round, requiring manual interruption and a manual rerun of the pipeline.

## Possible Improvements

1. Use of multiple bookmakers or an odds aggregation service to reduce dependence on a single pricing source. Betano was selected initially for scraping accessibility, not pricing accuracy.
2. Incorporation of additional bookmaker markets, including shots on target and card probability where available, using the same extraction method applied to scorer odds.
3. Backtesting against a complete tournament, including the group stage, to establish coefficient values prior to live deployment.

## Tech Stack

| Tool | Purpose |
|---|---|
| Python | Core language |
| pandas, numpy | Data handling |
| scikit learn, MinMaxScaler | Feature normalization |
| rapidfuzz | Player name matching |
| curl_cffi | Betano scraping |
| pyarrow | Parquet output |
| PuLP, CBC solver | Squad and transfer optimization |
| scipy.stats | Poisson and normal distribution calculations |
| Jupyter Notebook | Feature engineering and modeling environment |
| Betano API, Betclic gRPC Web endpoint | Odds data source |
| FIFA Fantasy API | Player and points data source |
| FBref | Club statistics, discontinued |
