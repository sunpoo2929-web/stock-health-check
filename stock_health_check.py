#!/usr/bin/env python3
"""
7 PM Stock Health Check — SET / DR / NASDAQ
================================================
ทุกวันทำการ 19:00 น.: ดึงราคาปิด → คำนวณ CDC Action Zone V3, RSI, Trend
→ เขียน docs/data.json (ให้ Dashboard บน iPhone) → ส่ง Exception Alert ทาง ntfy / Telegram

  python stock_health_check.py            ดึงข้อมูลจริง เขียน data.json และส่งแจ้งเตือน
  python stock_health_check.py --demo     ข้อมูลจำลอง (ทดสอบหน้าตา) ไม่ส่งแจ้งเตือน
  python stock_health_check.py --dry-run  ข้อมูลจริง เขียน data.json แต่ไม่ส่งแจ้งเตือน

แหล่งข้อมูล:  Yahoo Finance (หลัก)  ·  set.or.th (ดัชนี SET และสำรองของหุ้นไทย)
แจ้งเตือน (environment variables):
  NTFY_TOPIC                         แอป ntfy บน iPhone (แนะนำ ไม่ต้องสมัครสมาชิก)
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID   (ไม่บังคับ)
  DASHBOARD_URL                      ลิงก์ Dashboard (ถ้าไม่ใส่ จะเดาจากชื่อ GitHub repo)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

BKK = ZoneInfo("Asia/Bangkok")
HERE = Path(__file__).resolve().parent
DATA_JSON = HERE / "docs" / "data.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"

# ════════════════════════ Indicators ════════════════════════
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def cdc_action_zone_v3(df: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.DataFrame:
    """CDC Action Zone V3 (piriya33)
    src=OHLC4, AP=EMA(src,2), Fast=EMA(AP,12), Slow=EMA(AP,26)
      Bullish = Fast>Slow            Bearish = Fast<Slow
      Green   = Bull & AP>Fast       Red     = Bear & AP<Fast
      Yellow  = Bull & AP<Fast & AP>Slow   (Dip)
      Orange  = Bull & AP<Fast & AP<Slow   (Strong Dip)
      LBlue   = Bear & AP>Fast & AP<Slow   (Rally)
      Blue    = Bear & AP>Fast & AP>Slow   (Strong Rally)
      Buy Alert  = แท่งแรกที่เป็น Green  |  Sell Alert = แท่งแรกที่เป็น Red
      สถานะ BUY/SELL = Alert ล่าสุดที่เกิด
    """
    src = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    ap = ema(src, 2)
    f, s = ema(ap, fast), ema(ap, slow)
    bull, bear = f > s, f < s
    green = bull & (ap > f)
    red = bear & (ap < f)
    yellow = bull & (ap <= f) & (ap > s)
    orange = bull & (ap <= f) & (ap <= s)
    lblue = bear & (ap >= f) & (ap < s)
    blue = bear & (ap >= f) & (ap >= s)

    zone = pd.Series("none", index=df.index, dtype=object)
    for name, m in (("green", green), ("red", red), ("yellow", yellow),
                    ("orange", orange), ("lblue", lblue), ("blue", blue)):
        zone[m] = name

    buy_sig = green & ~green.shift(1, fill_value=False)
    sell_sig = red & ~red.shift(1, fill_value=False)
    sig = pd.Series(np.nan, index=df.index)
    sig[buy_sig] = 1
    sig[sell_sig] = -1
    state = sig.ffill().map({1: "BUY", -1: "SELL"}).fillna("-")
    return pd.DataFrame({"zone": zone, "state": state, "buy": buy_sig, "sell": sell_sig,
                         "bull": bull, "bear": bear, "fast": f, "slow": s})


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def trend(close: pd.Series, fast: int, slow: int) -> pd.Series:
    ef, es = ema(close, fast), ema(close, slow)
    t = pd.Series("Sideways", index=close.index, dtype=object)
    t[(close > ef) & (ef > es)] = "Uptrend"
    t[(close < ef) & (ef < es)] = "Downtrend"
    return t


ZONE_TH = {"green": "เขียว", "red": "แดง", "yellow": "เหลือง (ย่อ)", "orange": "ส้ม (ย่อแรง)",
           "lblue": "ฟ้าอ่อน (เด้ง)", "blue": "น้ำเงิน (เด้งแรง)", "none": "-"}


# ════════════════════════ Analysis + alerts ════════════════════════
def analyse(item: dict, df: pd.DataFrame, cfg: dict) -> dict:
    df = df.dropna(subset=["Close"]).copy()
    for c in ("Open", "High", "Low"):
        df[c] = df[c].fillna(df["Close"])
    cdc = cdc_action_zone_v3(df)
    r = rsi(df["Close"], cfg["rsi_period"])
    enough = len(df) >= cfg["trend_slow_ema"]
    tr = trend(df["Close"], cfg["trend_fast_ema"], cfg["trend_slow_ema"]) if enough \
        else pd.Series("n/a", index=df.index, dtype=object)
    e50 = ema(df["Close"], cfg["trend_fast_ema"])
    e200 = ema(df["Close"], cfg["trend_slow_ema"])
    vol_avg = df["Volume"].rolling(20).mean()

    c0, c1 = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
    chg = (c0 / c1 - 1) * 100
    z0, z1 = cdc["zone"].iloc[-1], cdc["zone"].iloc[-2]
    s0, s1 = cdc["state"].iloc[-1], cdc["state"].iloc[-2]
    t0, t1 = tr.iloc[-1], tr.iloc[-2]
    r0, r1 = float(r.iloc[-1]), float(r.iloc[-2])
    status = item.get("status", "accumulate")
    holds = status in ("holding", "accumulate")
    wants_more = status in ("accumulate", "waiting")
    is_index = item.get("group") == "index"
    alerts: list[dict] = []

    def A(p, icon, text, action):
        alerts.append({"p": p, "icon": icon, "text": text, "action": action})

    # 1) CDC flip
    if s1 == "BUY" and s0 == "SELL":
        A(1, "🔴", "CDC V3 เปลี่ยน Buy → Sell (Sell Alert)",
          "หยุดสะสมก่อน ทบทวนแผน/จุด Stop ของไม้ที่ถือ" if holds else "ยังไม่ควรเข้า รอสัญญาณกลับตัว")
    elif s1 == "SELL" and s0 == "BUY":
        A(2 if holds else 1, "🟢", "CDC V3 เปลี่ยน Sell → Buy (Buy Alert)",
          "เริ่มรอบขาขึ้นใหม่ — จังหวะทยอยสะสม" if wants_more else "สัญญาณกลับมาเป็นบวก ถือต่อตามแผน")

    # 2) ย่อในขาขึ้น = จังหวะสะสม (เฉพาะคนที่อยากซื้อเพิ่ม)
    if wants_more and z0 in ("yellow", "orange") and z1 not in ("yellow", "orange") and t0 != "Downtrend":
        A(2, "🟡" if z0 == "yellow" else "🟠",
          f"ย่อตัวในขาขึ้น — CDC เป็น{ZONE_TH[z0]}",
          "แนวโน้มหลักยังเป็น Bullish — โซนทยอยสะสม (รอแท่งกลับเขียวเพื่อยืนยัน)")

    # 3) Trend change
    if t0 == "Downtrend" and t1 != "Downtrend":
        A(1, "📉", f"Trend เปลี่ยน {t1} → Downtrend", "ราคาหลุด EMA50 และ EMA50 < EMA200 — เทรนด์ระยะกลางเสีย ชะลอการสะสม")
    elif t0 == "Uptrend" and t1 != "Uptrend" and t1 != "n/a":
        A(3, "📈", f"Trend เปลี่ยน {t1} → Uptrend", "เทรนด์ระยะกลางกลับเป็นขาขึ้น")
    elif holds and t1 == "Uptrend" and t0 == "Sideways":
        A(3, "⚠️", "หลุดออกจาก Uptrend (ราคาต่ำกว่า EMA50)", "เฝ้าดูว่าจะเสียเทรนด์ต่อหรือไม่")

    # 4) ลงแรงผิดปกติ
    thr = cfg["drop_alert_pct_index"] if is_index else cfg["drop_alert_pct"]
    if chg <= -thr:
        vx = float(df["Volume"].iloc[-1] / vol_avg.iloc[-1]) if vol_avg.iloc[-1] else 0.0
        vtxt = f" · วอลุ่ม {vx:.1f} เท่าของค่าเฉลี่ย" if vx >= cfg["volume_spike_x"] else ""
        A(1, "⚡", f"ราคาลงแรง {chg:.1f}%{vtxt}",
          "เช็กข่าว/งบ ก่อนตัดสินใจ" + (" — วอลุ่มหนุน แรงขายจริง" if vtxt else ""))

    # 5) RSI
    if r0 >= cfg["rsi_overbought"] > r1:
        A(3, "🌡️", f"RSI ขึ้นเขต Overbought ({r0:.0f})", "ร้อนแรง — ไม่ควรไล่ซื้อเพิ่มตอนนี้")
    elif r0 <= cfg["rsi_oversold"] < r1:
        A(2 if wants_more else 3, "🧊", f"RSI ลงเขต Oversold ({r0:.0f})",
          "ขายมากเกินไป — อาจใกล้เด้ง รอ CDC ยืนยันก่อนสะสม")

    # 6) Buy zone (ถ้าตั้งไว้)
    bz = item.get("buy_zone")
    if wants_more and bz:
        lo, hi = bz
        if lo <= c0 <= hi and not (lo <= c1 <= hi):
            ok = s0 == "BUY"
            A(1 if ok else 2, "🎯", f"เข้า Buy Zone {lo:g}–{hi:g}" + (" + CDC เป็น Buy" if ok else " (CDC ยัง Sell)"),
              "ถึงราคาที่วางแผนไว้ — เตรียมแบ่งไม้สะสม")
        elif c0 < lo <= c1:
            A(2, "⬇️", f"หลุดใต้ Buy Zone ({lo:g})", "ราคาต่ำกว่าเขตที่วางไว้ — ทบทวนโซนใหม่")

    alerts.sort(key=lambda a: a["p"])
    since = int((cdc["state"] != s0)[::-1].values.argmax()) if (cdc["state"] != s0).any() else len(cdc)
    n = cfg.get("history_days", 120)
    h = df.iloc[-n:]
    return {
        "symbol": item["symbol"], "name": item.get("name", item["symbol"]),
        "group": item.get("group", "th"), "status": status,
        "ticker": item.get("_ticker"), "source": item.get("_source"),
        "currency": item.get("_currency", "THB"), "close_only": bool(item.get("_close_only")),
        "as_of": df.index[-1].strftime("%Y-%m-%d"),
        "close": round(c0, 4), "chg_pct": round(chg, 2),
        "zone": z0, "zone_th": ZONE_TH[z0], "state": s0, "days_in_state": since,
        "flags": {
            "buy_alert": bool(cdc["buy"].iloc[-1]), "sell_alert": bool(cdc["sell"].iloc[-1]),
            "bullish": bool(cdc["bull"].iloc[-1]), "bearish": bool(cdc["bear"].iloc[-1]),
            "green": z0 == "green", "blue": z0 == "blue", "lblue": z0 == "lblue",
            "red": z0 == "red", "orange": z0 == "orange", "yellow": z0 == "yellow",
        },
        "rsi": round(r0, 1), "trend": t0,
        "ema50": round(float(e50.iloc[-1]), 4), "ema200": round(float(e200.iloc[-1]), 4) if enough else None,
        "buy_zone": bz, "alerts": alerts,
        "hist": {
            "d": [x.strftime("%Y-%m-%d") for x in h.index],
            "c": [round(float(x), 4) for x in h["Close"]],
            "f": [round(float(x), 4) for x in cdc["fast"].iloc[-n:]],
            "s": [round(float(x), 4) for x in cdc["slow"].iloc[-n:]],
            "z": list(cdc["zone"].iloc[-n:]),
        },
    }


# ════════════════════════ Data sources ════════════════════════
def _get_json(url: str, headers: dict | None = None, tries: int = 3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * i)
    raise RuntimeError(f"{url} → {last}")


def yahoo_ticker(item: dict) -> str:
    return item.get("underlying") or f"{item['symbol']}.BK"


def fetch_yahoo(ticker: str) -> tuple[pd.DataFrame, str]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?range=2y&interval=1d"
    try:
        j = _get_json(url)
        res = j["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        tz = ZoneInfo(res["meta"].get("exchangeTimezoneName", "UTC"))
        idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(tz).tz_localize(None).normalize()
        df = pd.DataFrame({"Open": q["open"], "High": q["high"], "Low": q["low"],
                           "Close": q["close"], "Volume": q["volume"]}, index=idx, dtype=float)
        df = df[~df.index.duplicated(keep="last")]
        return df, res["meta"].get("currency", "")
    except Exception as e:  # noqa: BLE001  -> fallback: yfinance (handles cookies/crumb)
        print(f"[info] Yahoo API ตรงใช้ไม่ได้ ({e}) ลอง yfinance", file=sys.stderr)
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period="2y", interval="1d", auto_adjust=False)
        if df.empty:
            raise RuntimeError(f"Yahoo ไม่มีข้อมูล {ticker}")
        df.index = df.index.tz_localize(None).normalize()
        return df[["Open", "High", "Low", "Close", "Volume"]], (t.fast_info.get("currency") or "")


SET_HDR = {"Referer": "https://www.set.or.th/th/market/index/set/overview", "Accept-Language": "th-TH,th;q=0.9"}


def fetch_set_index() -> pd.DataFrame:
    """ดัชนี SET จาก set.or.th — มีเฉพาะราคาปิด (Yahoo ไม่มีประวัติดัชนี SET)"""
    j = _get_json("https://www.set.or.th/api/set/index/SET/chart-quotation?period=5Y&accumulated=false", SET_HDR)
    q = j["quotations"]
    idx = pd.to_datetime([x["localDatetime"][:10] for x in q])
    c = [x["price"] for x in q]
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c,
                         "Volume": [x.get("volume") or 0 for x in q]}, index=idx, dtype=float)


def fetch_set_stock(symbol: str) -> pd.DataFrame:
    """สำรองสำหรับหุ้นไทย: set.or.th มี OHLC ย้อนหลัง ~6 เดือน (ไม่พอ EMA200)"""
    j = _get_json(f"https://www.set.or.th/api/set/stock/{urllib.parse.quote(symbol)}/historical-trading?lang=th",
                  {"Referer": f"https://www.set.or.th/th/market/product/stock/quote/{symbol}/historical-trading"})
    rows = sorted(j, key=lambda x: x["date"])
    return pd.DataFrame({"Open": [x["open"] for x in rows], "High": [x["high"] for x in rows],
                         "Low": [x["low"] for x in rows], "Close": [x["close"] for x in rows],
                         "Volume": [x.get("totalVolume") or 0 for x in rows]},
                        index=pd.to_datetime([x["date"][:10] for x in rows]), dtype=float)


def fetch_item(item: dict) -> pd.DataFrame | None:
    sym, grp = item["symbol"], item.get("group")
    try:
        if sym == "SET":
            item.update(_ticker="SET (set.or.th)", _source="set.or.th", _currency="pt", _close_only=True)
            return fetch_set_index()
        tk = yahoo_ticker(item)
        df, cur = fetch_yahoo(tk)
        item.update(_ticker=tk, _source="Yahoo Finance", _currency=cur or ("THB" if grp == "th" else ""))
        return df
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {sym}: แหล่งหลักล้มเหลว — {e}", file=sys.stderr)
        if grp == "th":
            try:
                item.update(_ticker=sym, _source="set.or.th (สำรอง)", _currency="THB")
                return fetch_set_stock(sym)
            except Exception as e2:  # noqa: BLE001
                print(f"[warn] {sym}: สำรองล้มเหลว — {e2}", file=sys.stderr)
        return None


def fetch_demo(stocks: list[dict], day: dt.date) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(14)
    idx = pd.bdate_range(end=pd.Timestamp(day), periods=480)
    out = {}
    for k, it in enumerate(stocks):
        sym = it["symbol"]
        mu = rng.normal(0.0004, 0.0006)
        ret = rng.normal(mu, 0.012 if it.get("group") != "dr" else 0.022, len(idx))
        tail = {  # scripted endings so every CDC status appears in the demo
            "PTT": [0.01, 0.008, -0.012, -0.015, -0.02, -0.034], "KTB": [-0.01, -0.012, 0.004, 0.012, 0.02, 0.022],
            "SCB": [0.006, 0.008, 0.004, -0.006, -0.01, -0.012], "TRUE": [-0.006, -0.01, -0.012, -0.008, 0.012, 0.018],
            "TSLA80": [0.03, -0.02, -0.03, -0.028, -0.025, -0.04], "LH": [-0.004] * 6,
            "NVDA01": [0.012, 0.015, 0.01, 0.018, 0.02, 0.025], "GULF": [0.005, -0.004, -0.009, -0.011, -0.014, -0.012],
        }.get(sym)
        if sym == "LH":
            ret[-60:] = rng.normal(-0.004, 0.008, 60)
        if tail:
            ret[-len(tail):] = tail
        base = {"SET": 1465.7, "NASDAQ": 24579.4, "BCP": 43.25, "PTT": 38.25, "PTTEP": 142.5, "GULF": 61.25,
                "KKP": 112.5, "KTB": 42, "SCB": 149, "WHA": 4.88, "AMATA": 26.25, "ADVANC": 338, "TRUE": 12.9,
                "TFG": 9.55, "LH": 3.5, "TAIWAN19": 72.4, "NVDA01": 188.2, "AMD80": 162.3, "GOOG80": 251.6,
                "TSLA80": 431.5}.get(sym, 40)
        close = base * np.exp(np.cumsum(ret) - np.cumsum(ret)[-1])
        op = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.002, len(close)))
        hi = np.maximum(op, close) * (1 + abs(rng.normal(0, 0.005, len(close))))
        lo = np.minimum(op, close) * (1 - abs(rng.normal(0, 0.005, len(close))))
        vol = rng.integers(2e6, 2e7, len(close)).astype(float)
        if sym == "PTT":
            vol[-1] *= 3.2
        df = pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": close, "Volume": vol}, index=idx)
        if sym == "SET":
            df[["Open", "High", "Low"]] = np.c_[close, close, close]
            it.update(_close_only=True, _source="set.or.th (จำลอง)", _ticker="SET", _currency="pt")
        else:
            it.update(_source="ข้อมูลจำลอง", _ticker=yahoo_ticker(it),
                      _currency="THB" if it.get("group") == "th" else ("TWD" if sym == "TAIWAN19" else "USD"))
        out[sym] = df
    return out


# ════════════════════════ Report text ════════════════════════
TH_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสฯ", "ศุกร์", "เสาร์", "อาทิตย์"]


def verdict(items: list[dict]) -> dict:
    p1 = [x for x in items if x["alerts"] and x["alerts"][0]["p"] == 1]
    p2 = [x for x in items if x["alerts"] and x["alerts"][0]["p"] == 2]
    if p1:
        head = f"วันนี้ต้องดู {len(p1)} ตัว" + (f" · จังหวะสะสม {len(p2)} ตัว" if p2 else "")
        level = "act"
    elif p2:
        head, level = f"ไม่มีเรื่องเร่งด่วน · จังหวะสะสม {len(p2)} ตัว", "watch"
    else:
        head, level = "วันนี้ไม่ต้องทำอะไร — ทุกตัวปกติ", "calm"
    return {"level": level, "headline": head, "act": [x["symbol"] for x in p1], "watch": [x["symbol"] for x in p2]}


def notify_text(items: list[dict], v: dict, max_lines: int = 14) -> str:
    """ข้อความสั้นสำหรับ push notification: 1 บรรทัดต่อหุ้นที่มี alert"""
    lines = []
    for x in sorted([i for i in items if i["alerts"] and i["alerts"][0]["p"] <= 2], key=lambda i: i["alerts"][0]["p"]):
        a = x["alerts"][0]
        more = f" (+{len(x['alerts']) - 1})" if len(x["alerts"]) > 1 else ""
        lines.append(f"{a['icon']} {x['symbol']} {x['chg_pct']:+.1f}% · {a['text']}{more}")
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"…และอีก {len(lines) - max_lines} ตัว"]
    if not lines:
        lines = ["ไม่มีสัญญาณเปลี่ยน ไม่ต้องทำอะไร"]
    return "\n".join(lines) + "\nแตะเพื่อเปิด Dashboard"


def full_text(items: list[dict], v: dict, day: dt.date) -> str:
    L = [f"🩺 7 PM Stock Health Check · {TH_DAYS[day.weekday()]} {day:%d/%m/%Y}", v["headline"], ""]
    for x in items:
        if not x["alerts"]:
            continue
        L.append(f"{x['alerts'][0]['icon']} {x['symbol']} {x['close']:,.2f} ({x['chg_pct']:+.1f}%)")
        for a in x["alerts"]:
            L.append(f"   • {a['text']}")
        L.append(f"   → {x['alerts'][0]['action']}")
    return "\n".join(L)


# ════════════════════════ Delivery ════════════════════════
def _post(url, payload, headers=None):
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def dashboard_url() -> str | None:
    if os.getenv("DASHBOARD_URL"):
        return os.getenv("DASHBOARD_URL")
    repo = os.getenv("GITHUB_REPOSITORY")  # owner/name (มีให้อัตโนมัติใน GitHub Actions)
    if repo:
        owner, name = repo.split("/")
        return f"https://{owner.lower()}.github.io/{name}/"
    return None


def deliver(items, v, day) -> list[str]:
    sent, url = [], dashboard_url()
    topic = os.getenv("NTFY_TOPIC")
    if topic:
        body = {"topic": topic, "title": f"🩺 7PM Health Check · {v['headline']}",
                "message": notify_text(items, v)[:3500],
                "priority": 4 if v["level"] == "act" else 3}
        if url:
            body["click"] = url
            body["actions"] = [{"action": "view", "label": "เปิด Dashboard", "url": url}]
        _post(os.getenv("NTFY_SERVER", "https://ntfy.sh"), body)
        sent.append("ntfy")
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        txt = full_text(items, v, day) + (f"\n\n📊 {url}" if url else "")
        _post(f"https://api.telegram.org/bot{tok}/sendMessage", {"chat_id": chat, "text": txt[:4000]})
        sent.append("Telegram")
    return sent


# ════════════════════════ Main ════════════════════════
def load_previous() -> dict:
    try:
        return {x["symbol"]: x for x in json.loads(DATA_JSON.read_text(encoding="utf-8"))["items"]}
    except Exception:  # noqa: BLE001
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "watchlist.yaml"))
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(DATA_JSON))
    args = ap.parse_args()

    conf = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    cfg, stocks = conf["settings"], conf["stocks"]
    for st in stocks:  # กัน YAML อ่าน TRUE/ON/NO เป็น boolean
        st["symbol"] = str(st["symbol"]).upper() if isinstance(st["symbol"], bool) else str(st["symbol"])
    now = dt.datetime.now(BKK)
    today = now.date()
    prev = {} if args.demo else load_previous()

    if args.demo:
        while today.weekday() > 4:
            today -= dt.timedelta(days=1)
        data = fetch_demo(stocks, today)
    else:
        # รอจนราคาปิดของวันนี้พร้อม (เช็กจากหุ้นไทยตัวแรก) — ถ้าไม่มีหลายรอบ = วันหยุดตลาด
        ref_item = next(s for s in stocks if s.get("group") == "th")
        wait_min = int(os.getenv("MAX_WAIT_MIN", "40"))
        force = os.getenv("FORCE") == "1"   # กดรันเอง: ใช้ราคาปิดล่าสุดที่มี แม้เป็นวันหยุด
        for attempt in range(wait_min // 10 + 1):
            ref = fetch_item(dict(ref_item))
            if ref is not None and force:
                today = ref.index[-1].date()
                break
            if ref is not None and ref.index[-1].date() == today:
                break
            if attempt < wait_min // 10:
                print(f"ยังไม่มีราคาปิดวันนี้ (ล่าสุด {None if ref is None else ref.index[-1].date()}) รอ 10 นาที…")
                time.sleep(600)
        else:
            print(f"ตลาดไทยไม่เปิดวันนี้ ({today}) — ไม่อัปเดตและไม่ส่งแจ้งเตือน")
            return
        data = {s["symbol"]: fetch_item(s) for s in stocks}

    items, missing = [], []
    for s in stocks:
        df = data.get(s["symbol"])
        if df is None or len(df.dropna(subset=["Close"])) < 60:
            missing.append(s["symbol"])
            continue
        x = analyse(s, df, cfg)
        # กันแจ้งซ้ำ: ตลาดต่างประเทศที่ยังไม่มีแท่งใหม่ (เช่นวันหยุดสหรัฐฯ) จะไม่ยิง alert ซ้ำ
        p = prev.get(x["symbol"])
        if p and p.get("as_of") == x["as_of"]:
            x["alerts"], x["stale"] = [], True
        else:
            x["stale"] = False
        items.append(x)

    order = {1: 0, 2: 1, 3: 2}
    items.sort(key=lambda x: (order.get(x["alerts"][0]["p"], 3) if x["alerts"] else 3,
                              ["index", "th", "dr"].index(x["group"]) if x["group"] in ("index", "th", "dr") else 9))
    v = verdict(items)
    payload = {
        "generated_at": now.isoformat(timespec="minutes"), "market_date": today.isoformat(),
        "demo": args.demo, "verdict": v, "missing": missing,
        "settings": {k: cfg[k] for k in ("rsi_overbought", "rsi_oversold", "drop_alert_pct")},
        "items": items,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(full_text(items, v, today))
    print(f"\n[data.json {out.stat().st_size/1024:.0f} KB · {len(items)} ตัว · ขาด {missing or '-'}]", file=sys.stderr)

    if args.demo or args.dry_run:
        print("\n--- push preview ---\n" + notify_text(items, v))
        return
    if v["level"] == "calm" and not cfg.get("send_when_no_alert", True):
        return
    sent = deliver(items, v, today)
    print("ส่งแล้วทาง: " + (", ".join(sent) if sent else "ยังไม่ได้ตั้งช่องทางแจ้งเตือน"))


if __name__ == "__main__":
    main()
