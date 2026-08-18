# World Cup 2026 Fantasy Optimizer

A probabilistic squad selection system built for FIFA's official World Cup 2026 fantasy game. The system combines bookmaker odds with FIFA fantasy platform data to compute expected fantasy points per player, then selects a valid squad using integer linear programming.

This project began during the Round of 16, with a 5th place in the standings as of that point.

<img width="1041" height="694" alt="ap25324491553100_jpg" src="https://github.com/user-attachments/assets/3d815a9f-c8d2-40f9-ae09-42a4e24cf822" />




## Repository Contents

1. `fifa_fantasy_data.py`. Retrieves player data, prices, positions, and round by round statistics from the FIFA fantasy API.
2. `fifa_players_full.json`. Raw output of `fifa_fantasy_data.py`.
3. `betano_parser.py`. Retrieves and parses Betano odds for match winner, both teams to score, totals, team totals, qualification, scorer markets and other odds.
4. `betano_odds.json`. Raw output of `betano_parser.py`.
5. `build_parquet.py`. Merges odds data with FIFA fantasy data.
6. `fantasy_optimizer.parquet`, `fantasy_optimizer.csv`. Merged dataset produced by `build_parquet.py`.
7. `match_log.txt`. Log of matched and unmatched player names produced during the fuzzy matching step in `build_parquet.py`.
8. `players_data-2025_2026.csv`, `players_data_light-2025_2026.csv`. Club level statistics exports from FBref, full and reduced versions. Associated with the discontinued club stats phase of the project.
9. `final_data_merging.ipynb`. Joins club level statistics to the merged FIFA and Betano dataset using edit distance name matching. Associated with the discontinued club stats phase.
10. `preprocess.ipynb`. Handles missing values and computes model input features, including per ninety minute rates and team and position stratified ranks.
11. `fantasy_enriched.csv`. Feature engineered dataset produced by `preprocess.ipynb`, consumed by `algorithm.ipynb`.
12. `algorithm.ipynb`. Contains the expected points model, the squad optimizer, and the transfer optimizer. Re executed each round.
13. `algorithm2.html`, `algorithm4.html`, `algorithm8.html`, `algorithm16.html`. Static exports of `algorithm.ipynb`, preserved as a record of the model at the final, semi final, quarter final, and round of 16 stages respectively.


## Data Sources

Two active data sources are used. Betano, for match and player odds, retrieved through its public API and the FIFA fantasy platform, for player prices, positions, point totals, and round by round statistics.

A third source, club level statistics from FBref, was used during early development and later discontinued.

## Impossibility to deploy a fully automated system

Deploying a fully automated model would have taken more time, which was a constraint in the development of this algorithm (during the few days window between Round of 32 for Round of 16). Not only that, but the needed database for such a project would need to very specific and treated carefully due to the "bubble" the World Cup represents in the context of competitive football:

1. Previous international friendlies and qualifiers might not reflect competitive tactics or full strength line-ups.
2. Club level statistics reflect a different context of team-mates, tactical systems, and opposition quality, and might not transfer reliably to international competition.
3. The only prior World Cup dataset is four years old and reflects a substantially different player pool in different form.

Such limitations is the reason this project is standing on bookies' shoulders, which will have a much more capable predicative model regardless and add a degree of an automation to the algorithm.

## Reliance on Bookmaker Odds

Bookmaker odds incorporate information, including squad news and internal tactical intelligence not available to this project. An independently constructed probability estimate was never going to outperform odds derived probabilities by multi million-dollar businesses even with perfect, complete available data. Betano odds were therefore treated as the primary signal for point sources such as goal scoring and clean sheet probability. 

## Club Level Statistics, Discontinued

FBref statistics were joined to FIFA player records initially. This source was discontinued, as more than half of the player pool competes outside the top five European leagues covered by FBref, resulting in low coverage (a complete dataset would need to cover all the way from the Canadian to the Australian league, with a dataset only covering the top 5 leagues ( less than 50% of the player pool ) adding an irrelevant signal.


## Methodology

### Probability Estimation

Implied probability is calculated as one divided by the decimal odd. Two way markets are de vigged by dividing each side's implied probability by the sum of both sides, removing bookmaker margin.

### Event Modeling

Some occurrence events, including red cards, conceded penalties, and own goals, are modelled using a sigmoid function applied to a weighted combination of input signals, each further scaled by a small maximum probability constant reflecting the real world rarity of the event. Yellow card probability is the one exception, computed as a weighted combination of input signals multiplied directly by the probability of playing 60 minutes, with no sigmoid transform applied.

Goals and assists are modelled by recovering a Poisson rate parameter from an estimated occurrence probability, using the relationship that the probability of zero occurrences equals the negative exponential of the rate. Solving for the rate gives the natural log of one minus the probability, negated. Since both are worth a fixed point value per occurrence with no bonus threshold, the recovered rate is used directly, multiplied by the relevant point value.

Tackles, chances created, and shots on target are recovered through the same rate transform and are subject to a bonus threshold, one point for every 3 tackles or every 2 chances created or shots on target.


### Missing Data Handling

Players with a confirmed fixture but no matched Betano scorer market entry were assigned a default any time scorer odd of 150, treating them as extreme long shots for goalscoring, such as backup goalkeepers and third string defenders. Round by round statistical columns with no recorded value, resulting from a player not participating in that round, were filled with zero, to keep aggregate and rolling statistics computable across the full player pool.

### Expected Points Calculation

Expected value is computed per scoring category. Goals are valued at 9 points for goalkeepers, 7 for defenders, 6 for midfielders, and 5 for forwards. Clean sheets are valued at 5 points for goalkeepers and defenders, 1 for midfielders, and 0 for forwards. Additional categories include appearance points, assists, a goals conceded penalty for goalkeepers and defenders, save and penalty save bonuses for goalkeepers, tackle and chance creation bonuses for midfielders, shots on target bonuses for forwards, card and own goal penalties, penalty win and concede adjustments, and a qualification bonus scaled by team advancement probability.

A differential, or scouting, bonus applies if a player is selected by fewer than 5 percent of managers and exceeds 4 base points in a match. This is modelled using a 90 percent Poisson confidence interval around expected base points. The full bonus is awarded if the lower bound exceeds 4 points. No bonus is awarded if the upper bound is below 4 points. If the interval spans 4 points, the bonus is scaled by the tail probability of exceeding 4 points given the expected value.

An elimination risk adjustment, introduced after the round of 16, subtracts an amount multiplied by the probability of the player's team not qualifying, applied after the differential bonus is calculated. This adjustment is additive rather than proportional, so it does not disproportionately reduce the expected points of high output players.

An attacking output penalty for goalkeepers and defenders, introduced after the round of 16, applies separately to goal scoring and assist rates. Goal scoring probability is set to zero for goalkeepers and multiplied by 0.7 for defenders. Assist rate is multiplied by 0.1 for goalkeepers and 0.9 for defenders. This addressed a pattern in which selections were inflated by low probability, high variance attacking outcomes, where defender and goalkeeping selections made were taking into account the potential offensive points rewards from the team variables included in their computation, which due to being team signals were much higher than the actual near-zero probability of a GK scoring offensive points.

### Squad Selection

Squad selection is formulated as an integer linear program and solved using the CBC solver. The objective maximizes total expected points across an 11 player starting lineup, with captain points doubled. Constraints include the budget, a 15 player squad composed of 2 goalkeepers, 5 defenders, 5 midfielders, and 3 forwards, a legal starting formation of 1 goalkeeper, 3 to 5 defenders, 3 to 5 midfielders, and 1 to 3 forwards, and a maximum players per nation.

### Transfer Optimization

Since this algorithm is meant to be deploy mid tournament into a player with a current team and performance, it is programmed to not necessarily predict the best possible team each round but specifically the best possible version of the player's current team taking into account transfer constraints. Each transfer beyond the fixed free transfer allowance is penalized by 3 points in the objective function, with the model determining if the penalty is worth it or not for all transfers possible.

## Round Summaries

### Round of 16

My team: Transfers. Out: Jordan Pickford, Sergiño Dest, Harry Kane, Jamal Musiala. In: Michael Olise, Mikel Oyarzabal, Emiliano Martínez, Achraf Hakimi.

A model error was identified in this round. Goal scoring probability for goalkeepers was not set to zero prior to squad selection, contributing to Emiliano Martínez being selected over Mike Maignan, which would end up costing 5-15 points down the line due to the difference in clean sheets from this point between Argentina and France.

Standing: Still 5th place, lower gap.


---


### Optimal squad selection: 



<img width="806" height="636" alt="image" src="https://github.com/user-attachments/assets/fdb6199e-5077-418e-8d37-590c99bccb5b" />

---

> Optimal squad selection result: 102 points, the highest recorded score in the private league for this round and a moderate outlier for the public leaderboard, with the optimal squad having the obvious advantage of drafting a team from scratch.

---

<img width="1296" height="729" alt="i" src="https://github.com/user-attachments/assets/43e8dc95-f6fb-4353-9304-b5166124be3e" />

### Quarter Finals

My team: Transfers. Out: Vinícius Júnior, Christian Pulisic, Camilo Vargas, Johan Manzambi. In: Brahim Díaz, Unai Simón, Jude Bellingham, Dani Olmo.

Standing: Still 5th place, lower gap.


---


### Optimal squad selection: 


<img width="779" height="711" alt="image" src="https://github.com/user-attachments/assets/c8e4ba5f-defe-4e65-9a39-db22609f1624" />

---

> Optimal squad selection result: 82 points, second place in the private league. Non booster teams on the wider leaderboard scored between 85 and 90 points in this round, with the algorithm showing a slight decrease in its still respectable predictability. 


---

<img width="1600" height="900" alt="skysports-kylian-mbappe-france_7294177_jpg" src="https://github.com/user-attachments/assets/8481055c-1270-423b-acfd-d41a57c11cdc" />


### Semi Finals

My team: Transfers. Out: Unai Simón, Facundo Medina, Emiliano Martínez, Brahim Díaz, Achraf Hakimi. In: Mike Maignan, Jordan Pickford, Nahuel Molina, Anthony Gordon, Lucas Digne.

The final selection deviated from 2 of the 5 transfers suggested by the model, with Anthony Gordon was selected in place of Adrien Rabiot, and Nahuel Molina in place of Cristian Romero. This followed an assessment that the model was undervaluing goal and assist probability in midfield selection relative to clean sheet and appearance probability, as well as the need to make bolder decisions in order to potentially close the gap. This specific model does not know no other opponent in the league had Gordon, which as a starting forward for England could potentially register a goal contribution that in this scenario would help severely close the gap.

Standing: 4th place, a much smaller gap to first.

---


### Optimal squad selection: 


<img width="820" height="684" alt="image" src="https://github.com/user-attachments/assets/5314cf14-8889-4adb-bbb1-add52083d021" />

---

> Optimal squad selection result: 56 points with a booster ( 1 goal conceded == clean sheet ), third place in the private league. Non booster teams on the wider leaderboard scored between 60 and 80 points in this round woith the model having a disastrous performance mainly attributed to zero goals scored by an odds favoured French attacking line.

---

<img width="1600" height="900" alt="Messi-vs-England_jpg" src="https://github.com/user-attachments/assets/5f798684-e62b-4b94-b22a-173dbef38646" />


### Final

My team: Transfers recommended by the model were not used, as the only chance for a possible victory was to do something extreme ( which would not be the algorithm's output ) and hope it would pay out, with the decision being going all in on Spain, hoping for a 3-0 or more win.

Final Standing: 2nd place.

Optimal recommended squad, expected points 81.98:

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

Optimal squad selection result: consistent with the round average, in the range of 75 to 80 points.

## Results

Round of 32 standing: 5th place, 377 points, -36 gap to first. Final standing: 2nd place, 670 points, -14 gap to first.

This algorithm allowed for a considerable shrinkage of the gap to the 4 players above in the first 2 rounds it was deployed.

However, if the team were to follow the algorithm's decisions in the semi-final round, the final results would have been slightly worse, with more risky decisions like overruling Anthony Gordon in the semi-final allowing to close the small gap to the above players. 

The model was also limited in performance by some initial coding mistakes, which were giving defenders and goalkeeper unrealistic scoring/assisting probabilities, and are likely to have cost the team anywhere from 5 to 20 points (for example as referenced above in Maignan, which was not chosen over Martinez in the r16 due to the Argentinian having a higher chance to score a goal. The French goalkeeper would go on to make 2 clean sheets after that against  Martinez's zero).


Both using its decisions in full and not using them at all would have resulted in a final worse points tally. 


This displays the correct usage of this algorithm, as it can serve as a decision maker help but cannot be deployed on its own, missing private league context, general footballing context and suffering from the lack of variance in the final rounds. 



Its main limitation was just that, the fact that it was used so late, with such a small amount of teams, players and variance. This is very visible by the quickly decreasing performance and more similar picks as the player pool shrinks.

---

<img width="1296" height="729" alt="r1691526_1296x729_16-9" src="https://github.com/user-attachments/assets/90c8d48a-cb99-41e6-9b52-59f2a8a164a9" />


## Model Evolution

After the round of 16, three changes were made. An attacking output penalty was applied to goalkeepers and defenders to stop the model from deciding defenders and goalkeepers based on scoring probabilities. A maximum combined goalkeepers and defenders per nation was added to reduce concentration risk in a single team's defense. Betano weighting for goal scoring probability was reduced from 0.80 to 0.70 in favor of tournament derived data.

After the semi final, scoring and assist coefficients were increased for midfielders. This followed an observed pattern in which the model favored players with higher clean sheet or appearance probability over players with comparable or higher scoring and assist probability, reducing the model's ability to identify high ceiling outcomes over high floor ones.

Additional coefficient adjustments were made across rounds without a corresponding written entry in this document. These changes reflect continuous, informal recalibration between rounds rather than a single fixed model version deployed throughout the tournament.

## Known Limitations

1. Team name resolution relies on hardcoded string matching and manually maintained Portuguese to English dictionaries. A slightly different bookmaker, tournament, or team naming convention would require manual reconfiguration and would break the code, with every team or player not initially matched fixed manually with strings.
2. In general the code is held together by duct tape and prayers at multiple points and not in good conditions to be replicated for future scenarios.
3. Due to the time constraint to get the model operational for the Round of 16, a lot of the code was either written in a rush or by AI after specific detailed human instructions. Everything works but it is less efficient and clean than it should be. Its not good code.
4. No abstraction layer separates data source specific logic from the remainder of the pipeline.
5. Model weights and thresholds are assigned manually based on football domain knowledge and trial and error from round to round ( using a very small very overfitted sample ) and not fitted from data.
6. Reliance on a single bookmaker introduces exposure to that bookmaker's individual pricing errors.
7. The model was not deployed from the start of the tournament. Full operation began at the round of 16, lowering the number of rounds available for calibration and excluding the group stage and round of 32 from live testing.
8. Predictive separation decreased as the tournament progressed, consistent with a narrowing player pool and reduced variance among remaining teams.
10. Player availability was patched manually in code ahead of each round, based on externally sourced injury and squad news, since the FIFA fantasy API status field did not reliably reflect real world unavailability in time for the selection deadline.

## Possible Improvements

1. Use of multiple bookmakers or an odds aggregation service to reduce dependence on a single pricing source. Betano was selected initially for scraping accessibility, not pricing accuracy. The aggregation of 3 to 5 sources would heavily improve the models's robustness.
2. Incorporation of bookmakers with additional market events, including shots on target and card probability where available, using the same extraction method applied to scorer odds.
3. Backtesting against a complete tournament, including the group stage, to establish coefficient values prior to live deployment.
4. A more efficient, cleaner code with better data treatment and feature engineering.

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
