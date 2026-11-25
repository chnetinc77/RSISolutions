# Dashboard (static, Vercel)

The dashboard is a static site in `web/` (no server, no open ports). It renders `web/data/state.json`, which `rsi publish` writes from the research memory.

```
research agent -> rsi publish --push -> GitHub (web/data/state.json) -> Vercel redeploys -> public dashboard
```

## Deploy on Vercel (once)
1. Vercel -> Add New Project -> import `chnetinc77/RSISolutions`.
2. Framework Preset: **Other**. Leave Build/Install commands empty. `vercel.json` already sets the output directory to `web`.
3. Optional: add a domain such as `rsi.flsilabs.space` under Project -> Domains.

## Update the data
```
cd /root/rsisolutions
python3 -m rsi publish --push
```
Hourly automatic updates (cron, `crontab -e`):
```
0 * * * * cd /root/rsisolutions && /usr/bin/python3 -m rsi publish --push >> /root/rsi-publish.log 2>&1
```
Needs stored git credentials on the server (`git config --global credential.helper store`, then push once manually).

## What is public
Everything in `state.json`: problem statements, strategies, experiment summaries, claims with verifier verdicts, lessons, journal status. No server paths, keys or IPs are included. Only publish if the research is meant to be public; if the repo is private, Vercel can still deploy it.

## Styling
Colours and fonts are CSS variables at the top of `web/style.css`. To match flsilabs.space exactly, copy its colour and font values into those variables.
