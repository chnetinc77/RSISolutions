// Live data source. The research server pushes a one-commit `live-data` branch every ~60s
// (python3 -m rsi run ... --live). Falls back to the bundled data/state.json if unreachable.
window.RSI_CONFIG = {
  liveUrl: "https://raw.githubusercontent.com/chnetinc77/RSISolutions/live-data/state.json",
  pollSeconds: 20
};
