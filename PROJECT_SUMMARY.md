# Project summary (as of 13 November 2026)

Research and alert system for crypto and US stocks. Everything runs on GitHub Actions in this repo; alerts go to Telegram and ntfy. **Nothing here places orders.** Every trading rule is either a backtest or a paper (virtual) account. Not financial advice.

## Where things stand in one paragraph

The only idea that has repeatedly survived testing is a **trend regime gate on BTC**: be IN while BTC's daily close is above both its 200-day and 50-day average, OUT (cash) otherwise. It is stable across settings, beats a time-shift placebo, and survives higher costs and delayed signals (labs 33, 34, 39). Altcoin selection rules built on top of it (trend baskets, volume breakouts, the swing scanner, support/reclaim trades) have **not** shown an edge over simply holding BTC or ETH while the gate is IN (labs 36-38), and the live crypto paper rules are losing (see below). Lab 40 tested the gate on BTC back to 2011 and tempers the 2020+ picture: it helped a lot in the 2018 and 2022 bears, helped little in 2012-16 (drawdown -73% vs -85%) and trailed buy-and-hold on return in 2012-16 and 2023-now. Over the whole history it improves return per unit of drawdown only modestly (Calmar 1.25 vs 1.10) and gives up upside in strong bulls. Treat it as a drawdown reducer, not a return booster. Labs 42-43 (13 Nov) found no weekly-average variant worth switching to and gave the open-interest filter its first number: a thin edge from two 2025 events (see below). Evidence is still thin: BTC/ETH chosen in hindsight and 46 labs run on the same history. Next real evidence comes from the forward paper accounts.

## What is running

| Part | Workflow | What it does |
|---|---|---|
| Regime alert (crypto) | `regime_alert.yml`, daily 00:50 UTC | IN/OUT state from BTC 200/50 **plus an open-interest warning**; red/orange/green light. The OI part was added after seeing data and is not part of the gate tested in lab 39; lab 43 tested it separately (modest, anecdotal edge). Binance public futures files supply the OI (not Binance US); `regime_log.csv` logs the 200d, 50d and OI flags separately every day, so plain gate vs OI version can be compared going forward with no code change. |
| Gate paper bot | `gate_paper.yml`, daily 01:25 UTC | Plain 200/50 gate, paper accounts for BTC, ETH and 50/50 vs buy-and-hold, started 30 Oct 2026. Alerts only on a flip. This is the **canonical forward test of the gate**. |
| Swing scanner | `swing_scan.yml`, nightly | Cross above 50-day + volume spike + BTC IN. Data collector only (lab 38). |
| Intraday watch / liquidations | `intraday_watch.yml`, `okx_liq.yml` | Early-warning notes. |
| Stocks regime alert | `stocks_regime_alert.yml` | S&P 500 200-day with a 2% band; the light uses the 50-day. |
| Paper tests | `trend_paper.yml`, `variants_paper.yml`, `basket_paper.yml`, `review.yml` | CROSS and RECLAIM crypto rules, regime variants, stock portfolios (40/40/20, 50/30/20 since 21 Oct). `review.py` writes `review_latest.txt`. |
| Token bot | `token_bot.yml` | Message a coin name, get a chart with support/resistance and a swing map. |

## Findings by area

**Crypto regime (labs 33, 34, 39).** The 200/50 gate sits on a plateau (125-300 day slow average, 20-100 day fast average all work; 25-27 of 27 settings beat buy-and-hold on return per unit of drawdown). Faster entries and hourly triggers did not beat it. Time-shift placebo percentile 97-99. Results hold at 0.5% costs and a 2-day delay. Drawdown roughly halves (about -40% vs -77%). Expect many small whipsaws.

**Open-interest warnings (labs 26-29, 33).** Crowded-positioning flags were tested against BTC falls. Several flags were tried, so some will look good by luck; the settings are fragile and were chosen after seeing data. See each summary file for the multiple-testing notes.

**Altcoin and basket rules (labs 22-25, 30, 31, 36-38).** Holding every top-100 coin above its averages loses badly; the BTC gate is what makes baskets work (lab 36-37). The volume-spike trigger beat random days in an event study (lab 37) but, run as an account, was no better than random uptrend entries and worse than BTC/ETH held while IN (lab 38).

**Chart-analyst claims (lab 35).** Four red weeks, buying the 50-week EMA touch, and adding on a break below it showed no real edge. Hidden bullish divergence was mildly positive but faded in the second half.

**Cost-basis proxy (lab 32).** Pink/blue VWAP crossover studied as a bottom signal; few events, treat as descriptive.

**Stocks (stocks1-2c, portfolio3, 3b).** Index regime backtests, a 30-stock basket (survivorship-flattered), growth/sector/leverage, "where is the money going", and combined core/trend/crypto portfolios. Seasonality, lead-lag and volume did not hold up. Paper accounts are too early to judge.

**Crypto paper rules (CROSS / RECLAIM, support-zone signals).** Live results since 15 Oct are far below the backtest (RECLAIM about -0.85R per trade, CROSS about -1R, support-zone crypto BUY SIGNAL about -0.8R; stock BUY SIGNAL about +0.1R). Caveats found on 6 Nov:
- The review counts legs, but each RECLAIM/CROSS signal opens three legs with the same entry and stop, so independent trades are one third of the counts shown.
- Trades are heavily clustered in time (one moment produced 132 signals). RECLAIM A rests on 2 distinct days, B on 4, C on 15.
- The backtest itself was close to zero: the EMA50-reclaim rows in lab 12 range from about -0.04R to +0.09R per trade, each with a margin of roughly +/-0.05R to +/-0.09R, and the edge over random entries was at most about +0.09R. The "+0.1R" quoted in alerts was the top of that range.
- Lab 41 (run 9 Nov) compared them with random entries on the same tokens, stops and targets in the same weeks. Random entries also lost (about -0.3R to -0.7R), so the market was hostile, but every rule was worse than random: RECLAIM C -0.31R (15 days, 95% interval -0.40 to -0.19), crypto BUY SIGNAL -0.51R (22 days), CROSS -0.74R (8 days); IN ZONE -0.18R could not be told from random. RECLAIM A and B rest on only 2 and 4 days. Likely cause: the rules buy bounces, and bounces fade in a falling market. Decision: keep collecting silently to about 30 distinct days (mid-December), retire if still below random; never use for real money.

## Regime episode lengths (lab 40, BTC 2011-2026, plain 200/50 gate)

- 195 completed episodes (98 IN, 97 OUT), about 13 flips a year (about 6-7 round trips, each a probable taxable disposal in the UK; check with an accountant).
- Half of all episodes last 5 days or less and 57-62% last 10 days or less: most flips are noise, but long episodes carry most days (IN 47%, OUT 53%).
- A typical IN episode loses (median BTC return -1.3%, mean +20%): trend-following pays through a few big trends.
- IN episodes that survive 5 days have a median 38 more days regardless of age. OUT episodes that reach 10 days have a median 20 more days, 20 days -> 31 more, 40 days -> 36 more: a long OUT period is a real downtrend, not one that is 'due to end'.
- On 9 Nov the gate had been OUT for 18 days (since 22 Oct), longer than 74% of past OUT episodes.

## Midterm-year thesis, weekly-average variants and the OI filter (labs 42-43, 13 Nov)

Prompted by an outside video (midterm years are bear years, Q4 drops, weekly averages and realized price as support). Run by explicit request, despite the lab freeze below.

- **Midterm / post-peak years (lab 42, Bitstamp 2011+):** Q4 was negative in all three post-peak years (2014 -18%, 2018 -44%, 2022 -15%; Q4 2026 -15% to date) against a median of +52% for the other 12 Q4s, 3 of which were negative. Exact chance of 3 of 3 negatives by luck is about 4.4% (1.6% to 6.4% depending on the base rate). Not strong evidence: the idea was chosen after seeing these years, n is 3, and midterm years are the same years as post-peak years of the halving cycle, so the two cannot be separated.
- **Gate in post-peak years:** average -15% vs -65% for buy-and-hold, worst drawdown about -23% vs -72%; flat in all three Q4s, without knowing the year type. In other years it gives up upside (about +311% vs +711% average, mostly 2013 and 2017).
- **Weekly-average variants (16 gates, 100 to 400 days):** the whole family earns Calmar about 1.1 to 1.45 vs 1.01 for buy-and-hold; live 200/50 is 1.23 (placebo p 0.02, 181 switches). Four variants beat it in both halves, but differences are small, best-of-16 selection applies, and the 21-week EMA falls to 0.50 vs 0.98 for the live gate on the 2021+ window (lab 43). No reason to switch. The result depends strongly on the window: 200-day only is as good as 200/50 over 2012+ but far worse since 2021.
- **Open-interest filter (lab 43, 11 May 2021 to 12 Nov 2026, same code as the live alert):** live alert Calmar 1.20 vs 0.98 for the plain 200/50 gate (buy-and-hold 0.06); first half tied (0.94 each), second half 1.50 vs 1.04; identical in the 2022 bear. The whole difference comes from the 2022-25 rally (x4.11 vs x3.66) and since the 2025 top (x1.16 vs x1.03), mainly the warnings on 6 Oct 2025 (the top, then -17% in 30 days) and 17 Nov 2025. Of 16 warning episodes, 62% saw a 10%+ dip within 30 days (34% of all days), but the rule was fitted on this same data, one episode flagged the 2021 top only about six weeks late, and a few warnings were followed by rises. Verdict: a modest, anecdotal add-on; keep it, keep both versions running, judge on the forward log.
- **Realized price:** not tested (Coin Metrics returned HTTP 403 from the runner).

## Gate improvements (lab 44, 13 Nov)

Five ideas declared in advance, each tested alone against the live 200/50 gate on 2012+ (A) and 2021+ (B), with a written pass bar. **None passed; the gate stays as it is.**

- **Fast exit (out while 15% or 20% below the 60-day high):** the standout on 2012+ (Calmar 2.02 and 1.87 vs 1.23; drawdown -49% and -54% vs -73%), but all of it comes from 2012-2019. Since 2021 it is worse (15%: 0.72 vs 0.98) or never triggers (20%: identical). Earlier-era volatility, not a lasting edge.
- **2-close confirmation:** better on 2012+ (1.34 vs 1.23, both halves) with about 40% fewer flips (7.7 vs 12.9 a year), but worse since 2021 (0.70 vs 0.98). Its only failed check was the 2021+ window. Fewer flips would also mean fewer taxable disposals; a possible choice, not a recommendation.
- **2% band, graded 100/50/0 exposure, rising 200-day, S&P 500 above its 200-day:** no gain (the last two clearly worse). BTC was OUT while the S&P was above its 200-day on 12 Nov.
- **Lesson:** tweaks that help the early, wilder years do not help the recent regime. Any change is era-dependent, so the simple gate is kept. Combinations were not tested.

## Return boosters (labs 45-46, 16 Nov)

Ideas from a literature scan, declared in advance, tested on BTC and on US stocks (SPY, dividends reinvested) with a written pass bar. Only the free one passed.

- **T-bill interest on cash while OUT (passes, small):** BTC CAGR 91% vs 90% over 2012+, and 27% vs 25% since 2021 (4.12% T-bill, OUT about 55% of days). Earlier crypto labs let cash earn 0%. Stocks: about +1 point.
- **Volatility-sized exposure (target 50% vol, weekly):** the strongest result, but it mainly cuts risk. Capped at 1x: Calmar 2.08 vs 1.26 and worst drawdown -41% vs -73% over 2012+, for a slightly lower CAGR (85% vs 91%). Capped at 2x (borrowing 8% a year): CAGR 101%, drawdown still -41%, since 2021 CAGR 32% vs 27% at the same -25% drawdown. It missed the declared bar only on a tie in the second-half CAGR (48% vs 48%), so officially fail. Needs a robustness test across target volatility and update frequency before any paper account.
- **Lab 46 (27-setting robustness test of the volatility sizing): the "more gain" claim FAILED the declared plateau rule** (8 of 18 borrowing variants beat the baseline, 14 needed; same under doubled costs and 12% borrowing). What the grid shows instead is a **risk dial**: the sizing target sets the trade. Targets of 35% and 50% cut risk by design (all 9 no-leverage variants improved Calmar and shrank the worst drawdown in both windows: e.g. 35%, weekly, no leverage: Calmar 2.18 vs 1.26, drawdown -30% vs -73%, but CAGR 65% vs 91%). A 65% target earned more (CAGR 96% to 136% vs 91%; since 2021 up to 40% vs 27%) with average exposure 0.54 vs 0.46, but since 2021 the worst drawdown was -30% vs -25% and the best versions use up to 2x leverage at 8% borrowing. Worst single day: -48.5% for the plain gate vs -20% to -56% for sized versions. Choosing the 65% region now would be picking the winner after the fact; if wanted, it must be judged forward in a paper account. No change to the live gate or paper bot.
- **Donchian ensemble (9 lookbacks):** worse on BTC (7% CAGR since 2021 vs 27%). On SPY it cut drawdown (-10% vs -34% since 2012) but earned about half the buy-and-hold return.
- **Fixed 1.5x leverage:** BTC CAGR 129% but worst drawdown -89%. More gain here is simply more risk.
- **Stocks:** buy-and-hold beat every timing rule on raw gain (SPY 8% a year since 2000 vs at most 3%; 14% vs at most 7% since 2012). The rules only cut drawdowns.
- **Both together (50/50 BTC and SPY gates):** smoother, not bigger. Since 2021 CAGR 17% with drawdown -16% (vs 11% and -54% for 50/50 buy-and-hold), but less gain than the BTC gate alone (27%, -25%). Over 2012+ it earns less than 50/50 buy-and-hold (47% vs 56%).
- Nothing changes the live gate or paper bot. Historic CAGRs (BTC 2012-2019 especially) are not expectations.

## Cycle comparison and ETF flows (cycle_compare, lab 47, 16 Nov)
- **Cycle comparison (Bitstamp closes to 15 Nov 2026).** Peak to low: 2013-14 -85% (406 days), 2017-18 -83% (364), 2021-22 -77% (378), 2025-now -53% (267; peak 124,728 on 6 Oct 2025, low 58,526 on 30 Jun 2026). At day 405 the earlier cycles stood at -80%, -81%, -75% from the peak; today is -48%. The three earlier lows came on days 364 to 406; this one came about 100 days earlier. The first IN after each earlier low came 166, 108 and 53 days later with BTC already +49%, +54%, +26% above it; this cycle's first IN (19 Aug 2026, +17% over 64 days) failed on 22 Oct. Today's price is +12% above the June low; a flip IN needs a close above about 79,758 (+22%). Two readings fit (June was the low, or a retest is still due); the data cannot separate them and no probability is given.
- **Lab 47 (ETF flows, 2024-01-11 on, one bull and one bear).** Flow window grid W = 3 to 60 sessions; filter, boost and flow-only variants against the plain gate (Calmar 0.91, CAGR 22%, drawdown -25%). Pre-declared rule (5 of 6 windows beat the gate on Calmar and CAGR, also under costs x2 and a 1-day later decision): all three FAIL (best: boost, 2 to 3 of 6). Nothing adopted. The daily flow log (etf_flows.csv, TFTC data.json, CC BY 4.0) keeps running as a forward record.

## Labs index (newest first, from 26)

| Lab | Question | Status |
|---|---|---|
| 46 | Is the volatility-sized gate a real edge or a lucky setting (27 settings, stresses)? | done: 'more gain' failed the plateau rule; works as a risk dial, no free lunch |
| 45 | Return boosters on BTC and stocks (T-bill cash, vol-sized exposure, Donchian ensemble, leverage), and both together | done: only T-bill cash passed; vol-sizing is the best risk-adjusted lead, needs a robustness test; stocks beat every timing rule on raw gain |
| 44 | Can the 200/50 gate be improved (confirmation, band, graded exposure, fast exit, rising 200d, S&P)? | done: none passed the pre-declared bar; fast exit and confirmation help only on 2012-2019 data |
| 43 | Does the live alert's open-interest filter beat the plain 200/50 gate (2021+)? | done: modest edge from two 2025 events, tied in the first half; keep, judge on the forward log |
| 42 | Midterm/post-peak-year thesis; weekly-average gate variants | done: thesis suggestive but untestable (n=3); no variant worth switching to |
| 41 | Are the crypto paper rules worse than random entries in the same weeks? | done: yes, worse than random in a hostile market |
| 40 | How long do IN/OUT periods last; does the gate hold since 2011? | done: drawdown reducer, modest edge over 14 years; age does not predict the end of IN, long OUT periods tend to run on |
| 39 | How robust is the BTC 200/50 gate? | done: robust, with caveats |
| 38 | Portfolio simulation of the swing scanner rules | done: no edge over placebo or BTC/ETH hold |
| 37 | Controls and confidence intervals for lab 36 | done: BTC gate does the work |
| 36 | Top-100 coin trend baskets and the swing trigger | done |
| 35 | Chart-analyst claims | done: no real edge |
| 34 | Get in faster | done: nothing beat 200/50 |
| 33 | Regime robustness (settings, OI variants) | done: 200/50 on a plateau |
| 32 | Cost-basis crossover proxy | done: descriptive |
| 31 | Dip audit while the gate is on | done |
| 30 | Alts in the bull, out around tops | done |
| 29 | Does the OI warning replicate on other assets? | done |
| 28 | OI warnings with intraday, quadrants, filters | done |
| 27 | OI warning direction and dynamic detection | done |
| 26 | Futures positioning before BTC falls | done |

Earlier labs (2-25) cover the original support-zone finder, trend crosses, reclaims, model hunts and pullback anatomy. See `labN_summary.txt`.

## Working rules

1. Rules are frozen once a paper test starts; no tuning on live results.
2. The unit of evidence is a distinct day, not a trade or a leg. Judge a paper rule only after about 30 distinct signal days and at least one full IN/OUT cycle for regime rules.
3. Survivorship (today's coins and stocks only) and repeated testing on the same data flatter every backtest. Treat results as upper bounds.
4. New alerts and variants need a reason to exist beyond "more data"; extra variants raise selection risk.
5. Real money only after months of forward paper results, with a trade-only API key, small size, a kill switch and a tax check. The MEXC dry-run bot is parked until then.
6. Lab freeze: no new labs until the forward paper accounts reach about 30 distinct days. 46 labs on one history already make every new backtest result less trustworthy. Labs 42 to 46 were run by explicit request; the freeze otherwise stands.
7. Check this file and the repo before saying something does not exist or cannot be tested (the OI data and its daily log were missed once). Take current prices from the latest data or a live lookup, never from an earlier message.

## Open items

- Review the crypto paper rules again in mid-December (about 30 distinct days) and retire them if still below random entries.
- Intraday volume watch (`volume_watch.py`) was never uploaded; low priority, untested, and volume spikes did not predict returns on their own.
- Confirm the old Telegram bot is deleted.
- Re-run `stocks2d` for the corrected crypto dollar-volume rows.
- Open-interest filter: lab 43 gives it a modest, anecdotal edge. Keep both versions running and compare the plain gate with the OI version from `regime_log.csv` once there are several months of forward data; revisit then.
