# Project summary (as of 6 November 2026)

Research and alert system for crypto and US stocks. Everything runs on GitHub Actions in this repo; alerts go to Telegram and ntfy. **Nothing here places orders.** Every trading rule is either a backtest or a paper (virtual) account. Not financial advice.

## Where things stand in one paragraph

The only idea that has repeatedly survived testing is a **trend regime gate on BTC**: be IN while BTC's daily close is above both its 200-day and 50-day average, OUT (cash) otherwise. It is stable across settings, beats a time-shift placebo, and survives higher costs and delayed signals (labs 33, 34, 39). Altcoin selection rules built on top of it (trend baskets, volume breakouts, the swing scanner, support/reclaim trades) have **not** shown an edge over simply holding BTC or ETH while the gate is IN (labs 36-38), and the live crypto paper rules are losing (see below). Lab 40 tested the gate on BTC back to 2011 and tempers the 2020+ picture: it helped a lot in the 2018 and 2022 bears, helped little in 2012-16 (drawdown -73% vs -85%) and trailed buy-and-hold on return in 2012-16 and 2023-now. Over the whole history it improves return per unit of drawdown only modestly (Calmar 1.25 vs 1.10) and gives up upside in strong bulls. Treat it as a drawdown reducer, not a return booster. Evidence is still thin: BTC/ETH chosen in hindsight and 40+ labs run on the same history. Next real evidence comes from the forward paper accounts.

## What is running

| Part | Workflow | What it does |
|---|---|---|
| Regime alert (crypto) | `regime_alert.yml`, daily 00:50 UTC | IN/OUT state from BTC 200/50 **plus an open-interest warning**; red/orange/green light. The OI part was added after seeing data and is not part of the gate tested in lab 39. |
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

## Labs index (newest first, from 26)

| Lab | Question | Status |
|---|---|---|
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

## Open items

- Review the crypto paper rules again in mid-December (about 30 distinct days) and retire them if still below random entries.
- Intraday volume watch (`volume_watch.py`) was never uploaded; low priority, untested, and volume spikes did not predict returns on their own.
- Confirm the old Telegram bot is deleted.
- Re-run `stocks2d` for the corrected crypto dollar-volume rows.
- Decide whether the live regime alert keeps the open-interest filter or follows the plain gate the paper bot uses.
