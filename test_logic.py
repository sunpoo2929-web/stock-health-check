"""ทดสอบตรรกะ: alert ยิงถูกวัน ไม่ยิงซ้ำ และสีโซน CDC ตรงนิยาม"""
import numpy as np, pandas as pd, yaml
from stock_health_check import analyse, cdc_action_zone_v3, trend, ema

cfg = yaml.safe_load(open("watchlist.yaml"))["settings"]
rng = np.random.default_rng(1)
n = 900
close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
op = np.r_[close[0], close[:-1]]
df = pd.DataFrame({"Open": op, "High": np.maximum(op, close) * 1.005, "Low": np.minimum(op, close) * 0.995,
                   "Close": close, "Volume": 1e6}, index=pd.bdate_range("2023-01-02", periods=n))
item = {"symbol": "TEST", "group": "th", "status": "accumulate"}

cdc = cdc_action_zone_v3(df)
tr = trend(df["Close"], 50, 200)
checks = {
    "Buy → Sell": (cdc.state.shift() == "BUY") & (cdc.state == "SELL"),
    "Sell → Buy": (cdc.state.shift() == "SELL") & (cdc.state == "BUY"),
    "→ Downtrend": (tr.shift() != "Downtrend") & (tr == "Downtrend"),
}
for label, mask in checks.items():
    days = [i for i in np.where(mask)[0] if i > 250]
    hits = 0
    for i in days:
        x = analyse(item, df.iloc[: i + 1], cfg)
        hits += any(label in a["text"] for a in x["alerts"])
        if i + 2 <= n and not mask.iloc[i + 1]:
            y = analyse(item, df.iloc[: i + 2], cfg)
            assert not any(label in a["text"] for a in y["alerts"]), f"{label} ยิงซ้ำ"
    assert days and hits == len(days), (label, hits, len(days))
    print(f"OK  {label}: ยิงถูก {hits}/{len(days)} ครั้ง ไม่ยิงซ้ำ")

# zone definitions
src = (df.Open + df.High + df.Low + df.Close) / 4
ap = ema(src, 2); f = ema(ap, 12); s = ema(ap, 26)
z = cdc.zone
assert ((z == "blue") <= ((f < s) & (ap >= f) & (ap >= s))).all()          # Blue = Strong Rally (เหนือทั้งสองเส้น)
assert ((z == "lblue") <= ((f < s) & (ap >= f) & (ap < s))).all()          # Light Blue = Rally
assert ((z == "orange") <= ((f > s) & (ap <= f) & (ap <= s))).all()        # Orange = Strong Dip
assert ((z == "yellow") <= ((f > s) & (ap <= f) & (ap > s))).all()         # Yellow = Dip
assert (z != "none").iloc[30:].all()
print("OK  สีโซน CDC ตรงนิยาม:", dict(z.value_counts()))
x = analyse(item, df, cfg)
assert sum(x["flags"][k] for k in ("green", "blue", "lblue", "red", "orange", "yellow")) == 1
assert x["flags"]["bullish"] != x["flags"]["bearish"]
print("OK  flags ครบ 10 สถานะ")
