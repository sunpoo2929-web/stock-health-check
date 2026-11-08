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
# ราคาปิดดัชนี SET ย้อนหลัง (จาก set.or.th 10 ก.พ. 2568 – 6 พ.ย. 2569) ใช้ตั้งต้น เมื่อ set.or.th บล็อกเครื่องของ GitHub
SET_SEED = "20250210:1270.49,20250211:1283.97,20250213:1284.11,20250214:1272.1,20250217:1256.48,20250218:1257.48,20250219:1262.27,20250220:1245.61,20250221:1246.21,20250224:1235.85,20250225:1206.39,20250226:1231.14,20250227:1215.73,20250228:1203.72,20250303:1188.41,20250304:1177.64,20250305:1206.96,20250306:1189.55,20250307:1202.03,20250310:1177.44,20250311:1187.63,20250312:1160.06,20250313:1159.64,20250314:1173.76,20250317:1170.2,20250318:1176.17,20250319:1189.66,20250320:1181.71,20250321:1186.61,20250324:1190.06,20250325:1184.93,20250326:1190.36,20250327:1187.9,20250328:1175.45,20250331:1158.09,20250401:1168.02,20250402:1172.69,20250403:1161.81,20250404:1125.21,20250408:1074.59,20250409:1088.18,20250410:1133.95,20250411:1128.66,20250416:1138.9,20250417:1141.28,20250418:1150.95,20250421:1134.71,20250422:1144.05,20250423:1153.77,20250424:1146.86,20250425:1159,20250428:1159.53,20250429:1171.12,20250430:1197.26,20250502:1198.98,20250506:1187.86,20250507:1220.27,20250508:1206.59,20250509:1210.94,20250513:1214.39,20250514:1216.71,20250515:1194.49,20250516:1195.77,20250519:1187.06,20250520:1189.14,20250521:1179.81,20250522:1173.37,20250523:1176.36,20250526:1178.43,20250527:1163.42,20250528:1160.74,20250529:1164.01,20250530:1149.18,20250604:1132.02,20250605:1140.63,20250606:1136.43,20250609:1135.24,20250610:1139.16,20250611:1141.58,20250612:1128.62,20250613:1122.7,20250616:1114.49,20250617:1113.58,20250618:1094.58,20250619:1068.73,20250620:1067.63,20250623:1062.78,20250624:1100.01,20250625:1107.69,20250626:1106.73,20250627:1082.42,20250630:1089.56,20250701:1110.01,20250702:1115.69,20250703:1127.21,20250704:1119.94,20250707:1123,20250708:1115.65,20250709:1110.4,20250711:1121.13,20250714:1143.31,20250715:1161.01,20250716:1157.63,20250717:1198.11,20250718:1206.58,20250721:1208.13,20250722:1191.75,20250723:1219.62,20250724:1212.49,20250725:1217.15,20250729:1233.68,20250730:1244.14,20250731:1242.35,20250801:1218.33,20250804:1229.4,20250805:1246.96,20250806:1264.47,20250807:1265.15,20250808:1259.07,20250813:1277.43,20250814:1266.67,20250815:1259.42,20250818:1242.31,20250819:1235.76,20250820:1248.13,20250821:1244.79,20250822:1253.39,20250825:1262.67,20250826:1251.26,20250827:1248.03,20250828:1250.09,20250829:1236.61,20250901:1244.48,20250902:1248.78,20250903:1259.31,20250904:1252.55,20250905:1264.8,20250908:1266.11,20250909:1276.08,20250910:1278.05,20250911:1288.03,20250912:1293.62,20250915:1299.78,20250916:1308.19,20250917:1306.69,20250918:1297.01,20250919:1292.72,20250922:1282.54,20250923:1273.2,20250924:1278.41,20250925:1288.26,20250926:1278.74,20250929:1288.07,20250930:1274.17,20251001:1275.03,20251002:1288.29,20251003:1293.61,20251006:1285.64,20251007:1305.24,20251008:1304.92,20251009:1313.99,20251010:1286.98,20251014:1266.38,20251015:1286.69,20251016:1291.46,20251017:1274.61,20251020:1284.47,20251021:1290.72,20251022:1302.35,20251024:1313.91,20251027:1323.52,20251028:1314.28,20251029:1315.64,20251030:1314.65,20251031:1309.5,20251103:1308.86,20251104:1298.6,20251105:1295.29,20251106:1313.31,20251107:1302.91,20251110:1306.26,20251111:1300.47,20251112:1284.81,20251113:1287.44,20251114:1269.26,20251117:1280.07,20251118:1270.04,20251119:1272.17,20251120:1281.81,20251121:1254.4,20251124:1252.73,20251125:1268.78,20251126:1261.18,20251127:1252.71,20251128:1256.69,20251201:1276.57,20251202:1277.58,20251203:1274.82,20251204:1273.77,20251208:1261.39,20251209:1269.87,20251211:1253.54,20251212:1254.1,20251215:1273.4,20251216:1260.68,20251217:1256.85,20251218:1250.07,20251219:1252.19,20251222:1269.68,20251223:1271.11,20251224:1275.33,20251225:1264.77,20251226:1259.25,20251229:1254.03,20251230:1259.67,20260105:1280.05,20260106:1274.75,20260107:1280.82,20260108:1253.6,20260109:1254.09,20260112:1242.2,20260113:1235.3,20260114:1244.3,20260115:1261.39,20260116:1275.6,20260119:1283.2,20260120:1296.37,20260121:1317.56,20260122:1311.64,20260123:1314.39,20260126:1307.07,20260127:1334.45,20260128:1338.9,20260129:1331.07,20260130:1325.62,20260202:1321.42,20260203:1336.11,20260204:1346.54,20260205:1346.23,20260206:1354.01,20260209:1400.89,20260210:1410.44,20260211:1411.7,20260212:1441.53,20260213:1430.41,20260216:1438.09,20260217:1459.68,20260218:1466.67,20260219:1493.91,20260220:1479.71,20260223:1480.24,20260224:1490.4,20260225:1516.01,20260226:1533.64,20260227:1528.26,20260302:1466.51,20260304:1384.61,20260305:1417.29,20260306:1410.37,20260309:1382.97,20260310:1405.76,20260311:1407.34,20260312:1429.8,20260313:1409.35,20260316:1405.02,20260317:1433.88,20260318:1440.85,20260319:1417.45,20260320:1432.99,20260323:1397.34,20260324:1410.39,20260325:1457.91,20260326:1442.92,20260327:1447.05,20260330:1449.62,20260331:1448.14,20260401:1470.99,20260402:1465.72,20260403:1454,20260407:1464.43,20260408:1485.03,20260409:1489.66,20260410:1506.84,20260416:1489.73,20260417:1482.45,20260420:1481.85,20260421:1483.5,20260422:1479.74,20260423:1461.35,20260424:1456.1,20260427:1479.13,20260428:1480.2,20260429:1491.74,20260430:1493.69,20260505:1490.1,20260506:1516.91,20260507:1507.53,20260508:1500.36,20260511:1489.29,20260512:1483.56,20260513:1517.26,20260514:1539.12,20260515:1517.95,20260518:1517.74,20260519:1516.69,20260520:1528.43,20260521:1532.67,20260522:1538.67,20260525:1550.33,20260526:1553.36,20260527:1570.95,20260528:1568.97,20260529:1568.37,20260602:1588.06,20260604:1594.79,20260605:1582.6,20260608:1561.68,20260609:1584.14,20260610:1563.59,20260611:1572.32,20260612:1592.41,20260615:1591.72,20260616:1588.05,20260617:1587.07,20260618:1585.06,20260619:1572.5,20260622:1574.13,20260623:1540.9,20260624:1548.22,20260625:1558.55,20260626:1542.34,20260629:1577.81,20260630:1591.24,20260701:1588.23,20260702:1593.56,20260703:1611.28,20260706:1616.88,20260707:1604.13,20260708:1576.25,20260709:1608.3,20260710:1621.55,20260713:1627.9,20260714:1626.03,20260715:1630.21,20260716:1635.29,20260717:1639.04,20260720:1646,20260721:1652.97,20260722:1639.34,20260723:1641.03,20260724:1644.39,20260727:1624.47,20260730:1598.11,20260731:1623.64,20260803:1621.9,20260804:1617.13,20260805:1609.78,20260806:1614.64,20260807:1612,20260810:1624.36,20260811:1612.62,20260813:1614.36,20260814:1609.06,20260817:1626.44,20260818:1621.62,20260819:1609.76,20260820:1609.99,20260821:1613.78,20260824:1601.05,20260825:1596.01,20260826:1601.92,20260827:1600.7,20260828:1588.22,20260831:1595.16,20260901:1588.68,20260902:1575.07,20260903:1576.92,20260904:1595.58,20260907:1618.82,20260908:1621.89,20260909:1617.89,20260910:1615.07,20260911:1604.52,20260914:1591.07,20260915:1578.66,20260916:1562.73,20260917:1583.34,20260918:1584.15,20260921:1598.03,20260922:1604.44,20260923:1610.7,20260924:1602.58,20260925:1607.63,20260928:1602.37,20260929:1594.3,20260930:1559.01,20261001:1563.91,20261002:1571.62,20261005:1576.45,20261006:1582.22,20261007:1584.63,20261008:1570.61,20261009:1577.65,20261012:1571.74,20261014:1575.88,20261015:1573.01,20261019:1571.72,20261020:1554.94,20261021:1556.09,20261022:1562.67,20261026:1579.03,20261027:1575.02,20261028:1566.1,20261029:1544.6,20261030:1518.59,20261102:1507.2,20261103:1491.01,20261104:1502.09,20261105:1497.99,20261106:1465.7"
PREV_RAW: dict = {}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"

# ════════════════════════ Indicators ════════════════════════
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def cdc_action_zone_v3(df: pd.DataFrame, fast: int = 12, slow: int = 26, smooth: int = 1, source: str = "close") -> pd.DataFrame:
    """CDC Action Zone V3 (piriya33)
    src=ราคาตามที่ตั้ง (ค่าเริ่มต้น close), AP=EMA(src,smooth) [smooth=1 = ไม่ทำให้เรียบ], Fast=EMA(AP,12), Slow=EMA(AP,26)
    ตรงกับ TradingView "CDC ActionZone V3 2020 close 12 26 1"
      Bullish = Fast>Slow            Bearish = Fast<Slow
      Green   = Bull & AP>Fast       Red     = Bear & AP<Fast
      Yellow  = Bull & AP<Fast & AP>Slow   (Dip)
      Orange  = Bull & AP<Fast & AP<Slow   (Strong Dip)
      LBlue   = Bear & AP>Fast & AP<Slow   (Rally)
      Blue    = Bear & AP>Fast & AP>Slow   (Strong Rally)
      Buy Alert  = แท่งแรกที่เป็น Green  |  Sell Alert = แท่งแรกที่เป็น Red
      สถานะ BUY/SELL = Alert ล่าสุดที่เกิด
    """
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    src = {"close": c, "ohlc4": (o + h + l + c) / 4, "hlc3": (h + l + c) / 3, "hl2": (h + l) / 2}.get(source, c)
    ap = ema(src, smooth) if smooth > 1 else src
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


def stoch_rsi(close: pd.Series, k: int = 3, d: int = 3, rsi_len: int = 14, stoch_len: int = 14):
    """Stoch RSI แบบ TradingView: stoch(rsi, rsi, rsi, stoch_len) → K = SMA(…, k), D = SMA(K, d)"""
    r = rsi(close, rsi_len)
    lo, hi = r.rolling(stoch_len).min(), r.rolling(stoch_len).max()
    st = (r - lo) / (hi - lo).replace(0, np.nan) * 100
    kk = st.rolling(k).mean()
    return kk, kk.rolling(d).mean()


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
    cdc = cdc_action_zone_v3(df, cfg.get("cdc_fast", 12), cfg.get("cdc_slow", 26),
                             cfg.get("cdc_smooth", 1), cfg.get("cdc_source", "close"))
    r = rsi(df["Close"], cfg["rsi_period"])
    sk, sd = stoch_rsi(df["Close"], cfg.get("srsi_k", 3), cfg.get("srsi_d", 3),
                       cfg.get("srsi_rsi_len", 14), cfg.get("srsi_stoch_len", 14))
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

    # 5b) Stoch RSI (เส้น K ตัดเส้น D ในโซนสุดขั้ว)
    up_lv, lo_lv = cfg.get("srsi_upper", 80), cfg.get("srsi_lower", 20)
    k0, k1, d0, d1 = sk.iloc[-1], sk.iloc[-2], sd.iloc[-1], sd.iloc[-2]
    if not any(pd.isna(x) for x in (k0, k1, d0, d1)):
        if k1 <= d1 and k0 > d0 and d0 < lo_lv:
            A(2 if wants_more else 3, "🔼", f"Stoch RSI ตัดขึ้นในโซนต่ำ (K {k0:.0f} / D {d0:.0f})",
              "แรงขายเริ่มหมด เด้งจากโซนขายมากเกิน — ดู CDC ประกอบก่อนสะสม")
        elif k1 >= d1 and k0 < d0 and d0 > up_lv:
            A(3, "🔽", f"Stoch RSI ตัดลงในโซนสูง (K {k0:.0f} / D {d0:.0f})",
              "แรงซื้อเริ่มอ่อน — ไม่ควรไล่ซื้อเพิ่มช่วงนี้")

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
        "srsi_k": None if pd.isna(sk.iloc[-1]) else round(float(sk.iloc[-1]), 1),
        "srsi_d": None if pd.isna(sd.iloc[-1]) else round(float(sd.iloc[-1]), 1),
        "ema50": round(float(e50.iloc[-1]), 4), "ema200": round(float(e200.iloc[-1]), 4) if enough else None,
        "buy_zone": bz, "alerts": alerts,
        "hist": {
            "d": [x.strftime("%Y-%m-%d") for x in h.index],
            "c": [round(float(x), 4) for x in h["Close"]],
            "f": [round(float(x), 4) for x in cdc["fast"].iloc[-n:]],
            "s": [round(float(x), 4) for x in cdc["slow"].iloc[-n:]],
            "z": list(cdc["zone"].iloc[-n:]),
            "k": [None if pd.isna(x) else round(float(x), 1) for x in sk.iloc[-n:]],
            "sd": [None if pd.isna(x) else round(float(x), 1) for x in sd.iloc[-n:]],
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


def _set_series_to_df(d: list[str], c: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": [0.0] * len(c)},
                        index=pd.to_datetime(d), dtype=float)


def fetch_set_index() -> pd.DataFrame:
    """ดัชนี SET (มีเฉพาะราคาปิด)
    1) ลอง set.or.th ก่อน  2) ถ้าถูกบล็อก: ใช้ประวัติที่เก็บไว้ (SET_SEED + data.json รอบก่อน)
       แล้วต่อท้ายด้วยราคาปิดล่าสุดจาก Yahoo (^SET.BK มีแค่แท่งล่าสุด แต่พอสำหรับเติมวันละแท่ง)"""
    try:
        j = _get_json("https://www.set.or.th/api/set/index/SET/chart-quotation?period=5Y&accumulated=false", SET_HDR, tries=2)
        q = j["quotations"]
        series = {x["localDatetime"][:10]: float(x["price"]) for x in q}
        src = "set.or.th"
    except Exception as e:  # noqa: BLE001
        print(f"[info] set.or.th ใช้ไม่ได้ ({e}) → ใช้ประวัติที่เก็บไว้ + Yahoo", file=sys.stderr)
        series = {}
        for tok in SET_SEED.split(","):
            dd, cc = tok.split(":")
            series[f"{dd[:4]}-{dd[4:6]}-{dd[6:]}"] = float(cc)
        prev = PREV_RAW.get("set_index_series") or {}
        for dd, cc in zip(prev.get("d", []), prev.get("c", [])):
            series[dd] = float(cc)
        src = "ประวัติที่เก็บไว้ + Yahoo"
        try:
            j = _get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5ESET.BK?range=5d&interval=1d")
            res = j["chart"]["result"][0]
            ts, closes = res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]
            for t, c in zip(ts, closes):
                if c:
                    series[dt.datetime.fromtimestamp(t, BKK).strftime("%Y-%m-%d")] = round(float(c), 2)
        except Exception as e2:  # noqa: BLE001
            print(f"[warn] Yahoo ^SET.BK ใช้ไม่ได้ ({e2}) — ดัชนี SET จะเป็นข้อมูลของวันก่อน", file=sys.stderr)
    d = sorted(series)
    SET_STATE["series"] = {"d": d[-600:], "c": [series[x] for x in d[-600:]]}
    SET_STATE["source"] = src
    return _set_series_to_df(d, [series[x] for x in d])


SET_STATE: dict = {}


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
            df = fetch_set_index()
            item.update(_ticker="SET", _source=SET_STATE.get("source", "set.or.th"), _currency="pt", _close_only=True)
            return df
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
        raw = json.loads(DATA_JSON.read_text(encoding="utf-8"))
        if not raw.get("demo"):
            PREV_RAW.update(raw)
        return {x["symbol"]: x for x in raw["items"]}
    except Exception:  # noqa: BLE001
        return {}


def ensure_site_assets():
    """ไฟล์หน้าเว็บ: ถ้าอัปโหลดไฟล์ใหม่ไว้ที่หน้าแรกของ repo จะคัดลอกเข้า docs/ ให้ (เมื่อเนื้อหาต่างกัน)
    และถ้า docs/ ยังไม่มีไฟล์ จะหาจาก docs/docs/ — แล้ว stage ให้ workflow commit"""
    import shutil, subprocess
    for f in ("index.html", "manifest.webmanifest", "apple-touch-icon.png", "icon-192.png", "icon-512.png"):
        dst = HERE / "docs" / f
        root, nested = HERE / f, HERE / "docs" / "docs" / f
        src = None
        if root.exists() and (not dst.exists() or root.read_bytes() != dst.read_bytes()):
            src = root
        elif not dst.exists() and nested.exists():
            src = nested
        if src:
            shutil.copy2(src, dst)
            print(f"[fix] คัดลอก {src.relative_to(HERE)} → docs/{f}")
            if os.getenv("GITHUB_ACTIONS"):
                subprocess.run(["git", "add", str(dst)], cwd=HERE, check=False)


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

    if not args.demo:
        ensure_site_assets()
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
        "settings": {"rsi_overbought": cfg["rsi_overbought"], "rsi_oversold": cfg["rsi_oversold"],
                     "drop_alert_pct": cfg["drop_alert_pct"], "srsi_upper": cfg.get("srsi_upper", 80),
                     "srsi_lower": cfg.get("srsi_lower", 20),
                     "cdc": f'{cfg.get("cdc_source", "close")} {cfg.get("cdc_fast", 12)} {cfg.get("cdc_slow", 26)} {cfg.get("cdc_smooth", 1)}',
                     "srsi": f'{cfg.get("srsi_k", 3)} {cfg.get("srsi_d", 3)} {cfg.get("srsi_rsi_len", 14)} {cfg.get("srsi_stoch_len", 14)}'},
        "items": items,
    }
    if SET_STATE.get("series"):
        payload["set_index_series"] = SET_STATE["series"]
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
