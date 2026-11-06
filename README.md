# Scanner

Crypto and stocks regime alerts, paper-trading accounts and strategy labs, all running on GitHub Actions. Nothing here places real orders. Not financial advice.

Start with **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** for what is running, what the tests found, and what is still open.

## Layout

- `.github/workflows/*.yml`: every scheduled job and one-click lab. Labs are `workflow_dispatch` only (Actions tab, pick the lab, Run workflow).
- `backtest_labN.py` and `labN_summary.txt`: strategy labs and their written results. `labN_results.csv` hold raw output for some.
- `regime_alert.py`, `gate_paper.py`, `swing_scan.py`, `trend.py`, `basket_paper.py`, `paper.py`, `review.py`: live alerts and paper accounts.
- `scanner.py`, `backtest.py`: shared data loading, notifications and helpers.
- `*_state.json`, `*_log.csv`, `*_report.txt`: state and logs committed back by the workflows. Do not edit by hand.

## Running things

- Labs: Actions, choose "Strategy lab N", Run workflow. Results are committed as `labN_summary.txt`.
- Alerts need these repository secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NTFY_TOPIC`.
- Data comes from Binance US, OKX, Bitstamp, Yahoo Finance and Binance public data; most of these are blocked from some sandboxes, so labs are meant to run on GitHub Actions.
- Workflow files must live in `.github/workflows/`; copies elsewhere do nothing.
