# World Cup 2026 Fantasy Optimizer

A personal project to optimize squad selection for FIFA's official World Cup 2026 fantasy game. It scrapes bookmaker odds, merges them with FIFA's own fantasy data, and runs everything through a hand built expected points model and an integer program that picks the best legal squad it can afford.

## Why This Exists

I was fifth in my friends league. That's the whole origin story, honestly. I had a couple of free days between rounds and instead of doing something useful with them I decided to build an algorithm to stop being fifth. Everything below is the result of that.

## Repository Contents

1. `fifa_fantasy_data.py`, pulls player data, prices, positions, and round by round stats from FIFA's own fantasy API.
2. `betano_parser.py`, scrapes Betano's odds for every upcoming match and parses out match winner, both teams to score, totals, team totals, qualification, and scorer markets.
3. `build_parquet.py`, merges the two sources together, fuzzy matches FIFA player names against Betano scorer names, and outputs one row per player with every signal attached.
4. `preprocess.ipynb`, handles missing values, drops what didn't work, and engineers every feature the model uses (form, rates per ninety minutes, team and position stratified ranks, and so on).
5. `algorithm.ipynb`, the actual expected points model and the squad optimizer, plus a separate transfer optimizer for moving between rounds.

## Data Sources

The model runs on two live sources. Betano, for match and player odds, pulled through their public API and, for one particular match, through a Betclic gRPC Web endpoint that had to be reverse engineered field by field since there's no documentation for it anywhere. And FIFA's own fantasy platform, for player prices, positions, point totals, and round by round stats.

There used to be a third source, club level stats from FBref covering the top five European leagues. That one got dropped entirely, and the reasoning for that is worth its own section below.

## Why Not Machine Learning

The honest answer is there just isn't usable training data for this. International friendlies don't reflect real form or tactics since nobody takes them seriously, half the time it's a weakened squad testing fringe players. Club level stats reflect a completely different context, different teammates, different system, different quality of opposition, so they don't transfer cleanly to how someone performs for their country. And the only real prior World Cup data point is four years old, played by a mostly different generation of players in different form at a different age. That's not a dataset, that's one data point.

So rather than pretending there was enough signal to fit anything, I leaned on hand built probability estimates and let the market do the heavy lifting instead.

## Standing on Betano's Shoulders

The odds carry most of the weight in this model on purpose. Betano's traders have squad news, tactical information, and pricing models built on far more data than I could gather by myself in a couple of days. No matter how much time I spent tuning weights by hand, my own estimate of, say, Portugal's clean sheet probability was never going to beat what's already priced into their odds.

So instead of competing with that, I just stood on their shoulders. Their odds, de vigged into fair probabilities, are treated as the strongest available signal for things like goals, clean sheets, and match outcomes. My own effort went into the parts they don't price directly, the FIFA specific scoring mechanics, bonus thresholds, and the parts of the point system that have nothing to do with who wins the match.

## The Club Stats Detour

For a while I joined FBref club level stats onto each player, matched by name using Levenshtein distance within two characters of the FIFA name. It was even treated as a real signal for a while, ranked below odds and tournament stats in the weighting.

Eventually I dropped it completely. More than half the player pool plays outside the top five European leagues that FBref actually covers well, so the signal was patchy at best for a huge chunk of the players who actually matter. And even for the players it did cover, club form doesn't really tell you much about international form, different teammates, different system, different level of opponent every week. It wasn't worth the extra fuzzy matching complexity for a signal that wasn't reliable and probably wasn't that predictive anyway. What's left leans entirely on Betano odds, each player's own tournament stats so far, and plain football knowledge baked into the formulas below.

## The Math Behind It

**Odds into probabilities.** A decimal odd of two implies a fifty percent chance. That's just one divided by the odd. But bookmaker odds always bake in a margin, so both sides of a two way market add up to more than a hundred percent. To get a fair probability, each side's implied probability gets divided by the sum of both sides. That de vigging step is used everywhere a two way market shows up, both teams to score, over or under a goal line, and so on.

**Sigmoid for one off events.** Red cards, conceding a penalty, own goals, these can realistically only happen once per player per match, so a weighted combination of signals gets squeezed through a sigmoid to produce a clean probability between zero and one.

**Poisson for countable events.** Goals, assists, saves, tackles, shots on target, and chances created can all happen more than once in a match, and FIFA gives bonus points in chunks, a point for every three tackles, a point for every two chances created, and so on. A sigmoid caps out at one, which badly undersells a player who might rack up five or six of something in a single game. Instead, an estimated probability gets converted into a Poisson rate using the fact that the chance of zero occurrences equals the negative exponential of the rate, so the rate can be recovered by taking the negative log of one minus that probability. Once you have the rate, the expected number of occurrences is just the rate itself, since that's the definition of a Poisson mean, so bonus points fall straight out as rate divided by threshold, no further squashing needed.

**Stratified by team and position.** Comparing raw scoring odds across the whole player pool isn't fair, a mediocre striker will always look better than a great defender just because strikers score more. So price, minutes, starts, selection percentage, and scoring odds all get turned into percentile ranks within a player's own team and position group, so the question becomes is this the first choice striker for this team, not is this striker better than some elite center back.

**Expected points, category by category.** Every FIFA scoring category gets its own expected value, appearance points, goals (worth nine for a keeper, seven for a defender, six for a midfielder, five for a forward), assists, clean sheets (five for keepers and defenders, one for midfielders, zero for forwards), a goals conceded penalty for keepers and defenders only, save and penalty save bonuses for keepers only, tackle and chance creation bonuses for midfielders only, shots on target bonuses for forwards only, cards, own goals, penalties won and conceded, and a qualification bonus worth two points scaled by the odds implied probability that the player's team actually advances.

**The differential bonus.** FIFA gives an extra two points if a player is picked by fewer than five percent of managers and clears four base points in the match. Since that depends on an outcome that hasn't happened yet, it's modeled by treating expected base points as the mean of a Poisson distribution and building a ninety percent confidence interval around it. If even the low end already clears four points, the full two points get awarded. If the high end never gets there, zero. If the interval straddles four, the two points get scaled by the actual tail probability of exceeding four given that mean.

**Picking the squad.** The final selection is an integer program solved with the CBC solver, maximizing total expected points across a starting eleven, with the captain's points doubled and bench players discounted to sixty percent of their value since they only score if actually used. It respects a fixed budget, an exact position quota for the fifteen man squad, a legal formation range for the starting eleven, and a cap of four players from any single nation. A separate version of the same model starts from an existing squad and decides which transfers to make given a limited number of free transfers, docking three points from the objective for every transfer beyond that limit, while forced transfers, for a player who's no longer available, don't count against the free allowance since those weren't a choice.



## Known Fragility

I'll be straight about this. The code is held together by string matching from one end to the other. Every team name mapping, every market string check, every fuzzy name override is hardcoded around Betano's current Portuguese odds format and FIFA's current squad IDs. Point this at a different bookmaker, a different tournament, or even just a team whose name gets abbreviated differently, and it breaks immediately. There's no abstraction layer protecting against any of that, on purpose, because I had a couple of days between rounds and building something bulletproof was never the goal. Working well enough for right now was.

A lot of it was also written quickly with AI assistance because of the time pressure, and I'm not entirely happy about that. Some of it is messier and less careful than I'd write given more time. Pragmatism won over pride here, plainly.


## The Round of 16 Squad

Going into the round of 16 the model suggested four transfers, all within the free allowance. Out went Jordan Pickford, Sergiño Dest, Harry Kane, and Jamal Musiala, the last one forced since he'd dropped out of contention entirely. In came Michael Olise, Mikel Oyarzabal, Emiliano Martínez, and Achraf Hakimi, with Kylian Mbappé kept on as captain.

I have to confess something here. For a while the model never zeroed out the goal scoring probability for goalkeepers, which meant a keeper's tiny nonzero chance of scoring was quietly stacking on top of everything else. That is a real part of why Emiliano Martínez got picked over Mike Maignan for this squad. I caught the bug and the position specific zeroing you'll find in the final expected points function is the fix, but it happened close enough to the deadline that I'm honestly not certain the goalkeeper pick would have gone the same way if I'd caught it a day sooner.


## Round of 16 Review

### Substitution Review

**Kane for Oyarzabal:** Terrible call, horrible. Bookies were putting a lot of faith in a Mexico defense that hadn't conceded, and while that held up for most of one of the best World Cup games so far, it didn't stop the best striker on the planet from getting a goal and an assist, with Bellingham turning in one of the tournament's best performances alongside him. Oyarzabal missed a clear chance and was invisible the whole game. Terrible call.

**Hakimi for Dest:** Amazing call. Best right back on the planet had a great game against a weak, scoreless Canada, while the USA got sent home conceding 3 and playing terribly. Picking the best right back alive isn't exactly revolutionary, but still a great call.

**Martinez (Maignan) for Pickford:** Both conceded 2 in hard matches, same points. But once I zeroed out expected goals for GKs, the algorithm's actual pick was Maignan, clean sheet in an easy game. Counting this one as amazing.

**Olise for Musiala:** Olise had his worst performance of the tournament against the WWE side that is Paraguay, so the swap didn't add much. Better midfield returns that round came from the predictable, common picks, Brahim and Jude, with Ounahi and Vanaken also putting up points.

Overall the striker swap was the genuinely terrible one, and it's heavily influential on its own. Bookies were unfavoring Kane at a large rate, enough that I checked if it was a Betano only thing or a general trend. It was general, a lot of value was placed on that scoreless Mexico defense.

### Result

Optimal selection still put up a great tally, 102 points, the most in my league (small sample size) and strong even against the wider fantasy leaderboard, very few teams hit 100. It had the advantage of unlimited picks versus the 4 transfer limited competitors, but still a good sign of what it can do.

<img width="806" height="636" alt="image" src="https://github.com/user-attachments/assets/fdb6199e-5077-418e-8d37-590c99bccb5b" />


### Highs and Lows

**Lows**

* Oyarzabal sucks, Kane is too good even if the opposition is too.
* Model kept overvaluing Embolo and I didn't catch it.
* Argentina's defense got hyped throughout the whole build. Didn't see it before, definitely didn't see it after.
* Oyarzabal really fucking sucks.
* Overvalued the French attack, all 4 attackers landed in the top 4 picks for their position. Outlier though, if that game got called correctly the story's totally different. I'll allow it.
* Undervalued Haaland, overvalued Brazil. Some outliers are harder to predict, but giving more expected points to Oyarzabal, Lautaro, Lukaku or Embolo is straight up disrespectful. Betano was genuinely undervaluing him, better odds on Julián Álvarez and some of the names above, including a benched Lukaku. Shows exactly why relying on one bookie is a real limitation here.

**Highs**

* Bottom 3 expected points GKs all conceded, 3 of the top 4 didn't, Argentina was the exception. Great.
* France clean sheet vs Paraguay.
* Dávinson Sánchez.
* Kept flagging Lukaku across iterations, thought that was dumb since he barely starts, but he kept scoring anyway. Good call tbh.
* Hakimi, Brahim, Morocco in general, it kept rating them way above Canada and it was dead right.
* Ignored Portugal in every iteration despite them being an obvious pick at some point. Great call.

### Changes Made

* GKs and defenders now take a penalty on attacking stats. Their chance of contributing that way is low and unpredictable, and they were getting inflated purely off the team level coefficient and the fact they get more expected points per goal (7/9)
* Goal scoring and clean sheet now weigh Betano about 10% less, tournament data picks up the slack. Should help with misses like Haaland and the Argentina/France clean sheet gap.
* Expected points get an adjustment using the odds of the team qualifying, so a pick likely to get eliminated, and need replacing, gets discounted for it.
* The algorithm will overpick 3 or even 4 defenders of the same team, especially after the devaluing of attacking possibilities for defenders. With that, the model will try to squeeze in as many defenders of the most likely clean sheet as it can. That however is the definition of putting all eggs in one basket, as since defenders will get most of their points for team achievements instead of personal ( clean sheet vs goal ), a single goal losing me 20 points and guaranteeing that at least half of my final defenders won't achieve a CS, with addiitonal goals losing me even more goals * 4. Thus, in order to spread out my team better, defenders must be capped to 2 of the same team.


## The Round of 8

**Transfers**
OUT: Vinícius Júnior, Christian Pulisic, Camilo Vargas, Johan Manzambi
IN: Brahim Díaz, Unai Simón, Jude Bellingham, Dani Olmo

**Squad** (Expected points: 100.54, Cost: $104.9M)

* GK Emiliano Martínez (Argentina) $5.0, 3.74 EP
* GK Unai Simón (Spain) $5.0, 4.11 EP
* DEF Marc Cucurella (Spain) $5.1, 5.86 EP
* DEF Lisandro Martínez (Argentina) $4.6, 4.45 EP
* DEF Nico O'Reilly (England) $4.7, 3.44 EP
* DEF Achraf Hakimi (Morocco) $6.0, 3.18 EP
* DEF Facundo Medina (Argentina) $4.0, 2.40 EP
* MID Michael Olise (France) $9.5, 8.61 EP
* MID Jude Bellingham (England) $8.3, 7.45 EP
* MID Ousmane Dembélé (France) $10.0, 7.26 EP
* MID Dani Olmo (Spain) $7.7, 5.43 EP [SCOUT]
* MID Brahim Díaz (Morocco) $6.4, 5.13 EP
* FWD Lionel Messi (Argentina) $10.0, 11.48 EP [C]
* FWD Kylian Mbappé (France) $10.5, 9.47 EP
* FWD Mikel Oyarzabal (Spain) $8.1, 7.05 EP

## The Round of 8 Review

### Substitution Review

**Brahim Díaz:** I understand the logic. He'd had a fantastic World Cup as part of Morocco's attack, carried the scouting bonus, and was set to start as their most advanced forward. Any chance of Morrocco scoring a goal would go through him. It still didn't turn out to be a good decision, mainly because of how strong France were and considering how my options were thin: I already had Olise, Jude, Dembélé and Olmo locked in, and the more likely alternatives were players like Álex Baena or Mac Allister, with teams like England still rotating through four wingers. I agreed with the logic and would have made the same call again going into the round. I'm not mad about it, but it wasn't a good decision.

**Jude Bellingham:** If anything, a round too late. Obviously the right call though, he scored two more goals and led England into the next round as the best player of the round. The most optimal choice, even if the most obvious one.

**Dani Olmo:** A good decision, an assist plus the scouting bonus. He didn't even end up the highest scoring midfielder on his own team, Merino and Fabián Ruiz both outscored him, but it's hard to ask the model to predict points from players which have been coming off the bench in this tournament. Out of Spain's regular starters, he was the best option over Baena, a benched Pedri, and Lamine, so overall the right choice.

**Unai Simón:** The decision came down to Spain's clean sheet versus France's. Every bookie gave Spain the slightly better chance, given their record of zero goals conceded so far and Morocco's stronger attack compared to Belgium's. They were wrong. France were the only team to keep a clean sheet, and the lack of French defenders on my team hurt me again. My mistake last round of not subbing in Maignan wasn't as costly then, thanks to Vargas's clean sheet, but it caught up with me here, having Maignan instead would have been an extra five points. Still no French defenders, despite them having conceded zero goals through the knockout stage. Any chance of a comeback was dead in the water with that.

### Result

The optimal selection put up an average tally, 82 points, coming second in my league and a few points behind the best non booster teams on the wider leaderboard (85 to 90). Variance seems to have hit a wall this week. Most good teams without a booster landed somewhere between 75 and 87 points, and a look at both my own eleven man league and the leaderboard shows the smallest gap yet between the most optimal teams and the average ones. That tracks, standings are unlikely to move much beyond the margin of error from here on, which makes sense as the player pool keeps shrinking. Everything unpredictable this round came from bench players suddenly delivering, such as high points from Doué, Ruiz, Merino and Álvarez, guys who've spent a lot of this World Cup on the bench. I can't really hold that against the model. Predicting bench points is a) not something you can do efficiently, and b) something I literally coded it not to attempt in the first place.

Once again, even without a booster, it still had the advantage of unlimited picks over the four transfer limited competitors, which is exactly why an above average result still isn't something I can be happy with. It didn't win my league, and it doesn't stand out on the leaderboard either. A truly optimal score this round would have been 86 to 90 points, and every team above 90 on the leaderboard was running a booster.

<img width="779" height="711" alt="image" src="https://github.com/user-attachments/assets/c8e4ba5f-defe-4e65-9a39-db22609f1624" />


### Highs and Lows

**Lows**

* Argentina's defense is still overvalued, and the model keeps doing it.
* Failed to prioritize any French defenders for the second round in a row. Brahim wasn't a bad shout, but it didn't pay off, and I think the model still doesn't grasp how far ahead France is of everyone else. It did include two French defenders in the optimal team, but prioritized Spain in my actual one.
* Mac Allister showed up in a lot of test iterations across both rounds, but never made it into an actual final squad. The best possible team can only be known in hindsight, but swapping an Argentine defender for a French one and adding an Argentine midfielder would have diversified the team significantly and, in practice, gained me another 20 points, since both scored across the last two rounds. If I'd caught the goalkeeper bug in time last round, Maignan over Emi, it might have freed up room to fit an Argentine player elsewhere, likely in midfield.

**Highs**

* Out of all of Spain's starting midfielders so far, Dani Olmo was indeed the right pick, even over Lamine, though the optimal team went with Baena.
* Jude.
* Two French defenders made the optimal team.

### Changes Made

No additional changes. It's hard to meaningfully tune the model off this little data and this little actual predictive variance. There are no obvious flaws or gaps to fix, I can't make it know Spain was about to concede their first goal, or that a bench player might get five minutes and score (fucking Merino). Sticking with this model for the rest of the tournament.

## Possible Improvements

The most obvious next step, if I ever get more than two days between rounds, would be pulling odds from several bookmakers or a proper odds aggregator API and averaging across them for a more robust, less single source probability. Betano was just the fastest one I could scrape without hitting a login wall, not necessarily the best one out there. I'm fully aware I'm resting on Betano's shoulders here, and that's a limitation as much as it is a choice.

It's also worth repeating plainly that none of this is a trained model. Every weight in every formula above was chosen by hand, based on football knowledge and gut feel, not fitted to anything. Treat it as an informed heuristic, not a prediction engine. Some bookmakers also publish player level odds for shots on target or being booked with a card, which could plug into the same framework the scorer odds already use. Betano just doesn't carry those markets, so those categories still lean entirely on tournament stats instead.

## Tech Stack

Python, pandas, numpy, and scikit learn's MinMaxScaler for the data side. rapidfuzz for name matching. curl_cffi for scraping Betano past its bot protection. pyarrow for the parquet output. PuLP with the CBC solver for the squad optimizer. scipy's stats module for the Poisson and normal distribution work. Jupyter notebooks throughout. A hand parsed Betclic gRPC Web endpoint for one match's odds. FIFA's own fantasy API for player data. FBref, used briefly for club stats, then dropped.
