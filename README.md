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

## Repository notes

- **Tests:** `python -m unittest discover tests -v` (offline, standard library only). Also runs on Actions when `scanner.py` or `tests/` change.
- **Dependencies:** most jobs need only the Python standard library. `requirements.txt` lists the extras used by labs 24/25 and the token bot (each installs them in its own workflow).
- **Lab scripts are deliberately left as separate files.** Every `lab*.yml` has a `push: paths:` trigger on its own script, so editing a `backtest_labN.py` re-runs that lab (up to 4 hours). Refactor them only on a branch with the triggers removed.
- **Generated files** (`*_state.json`, logs, `chart_data.json`, signal CSVs) are committed back by the bots, so the repo only grows. If it gets unwieldy, move them to a separate `data` branch.
- **Public repo:** anyone can read the strategies and paper results. Make it private before any real edge is found or any real money is involved (Settings > General > Danger Zone).
- **Errors:** `scanner.py` prints `WARNING:` lines to the Actions log when it cannot read or write a state file or a data source, instead of failing silently.
