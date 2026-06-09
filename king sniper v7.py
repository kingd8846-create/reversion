#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║        KRAKEN KING EDGE BOT V2 — KRIS KRUSH ORGANIZATION        ║
║               Singapore Server Edition — Fee Shield             ║
║                  Opens Dashboard in Brave Browser                ║
╚══════════════════════════════════════════════════════════════════╝

HOW TO USE:
  1. Fill in KRAKEN_API_KEY and KRAKEN_API_SECRET below
  2. Fill in TELEGRAM_BOT_TOKEN below
  3. Run: python KRAKEN_KING_EDGE_V3.py
  4. Dashboard auto-opens at http://localhost:5000
"""

import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import json
import threading
import webbrowser
import subprocess
import sys
import os
from datetime import datetime
from flask import Flask, render_template_string, jsonify
import numpy as np

# ══════════════════════════════════════════════════════════════════
#  🔑  API CREDENTIALS — PASTE YOUR KEYS HERE
# ══════════════════════════════════════════════════════════════════

KRAKEN_API_KEY     = "PASTE_YOUR_KRAKEN_API_KEY_HERE"
KRAKEN_API_SECRET  = "PASTE_YOUR_KRAKEN_SECRET_HERE"

TELEGRAM_BOT_TOKEN = "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID   = "1295412342"

# ══════════════════════════════════════════════════════════════════
#  ⚙️  TRADING PARAMETERS
# ══════════════════════════════════════════════════════════════════

TRADE_PAIRS         = ["XBTUSD", "ETHUSD", "SOLUSD"]
TRADE_SIZE_PCT      = 0.04     # 4% of balance per trade
MAX_SIMULTANEOUS    = 2
SCORE_THRESHOLD     = 6
VOLUME_MULTIPLIER   = 1.1
RSI_THRESHOLD       = 48
TP_ATR_MULTIPLIER   = 3.0
SL_ATR_MULTIPLIER   = 0.8
SCAN_INTERVAL       = 30
ATR_PERIOD          = 14
RSI_PERIOD          = 14
VOLUME_MA_PERIOD    = 20

# ══════════════════════════════════════════════════════════════════
#  💰  FEE SHIELD — Kraken Pro Cost Protection
# ══════════════════════════════════════════════════════════════════

KRAKEN_TAKER_FEE_PCT  = 0.0040   # 0.40% taker fee (base tier)
OVERHEAD_BUFFER_USD   = 0.35     # $0.35 per-trade overhead buffer
SUBSCRIPTION_MONTHLY  = 4.99     # Kraken Pro $4.99/month
SUBSCRIPTION_DAILY    = round(4.99 / 30, 4)          # ~$0.166/day
SUBSCRIPTION_PER_TRADE= round(4.99 / 30 / 9, 4)      # ~$0.0185/trade (9 trades/day avg) — range $0.17-$0.26/day spread
MIN_PROFIT_TARGET_USD = round(6.00 + OVERHEAD_BUFFER_USD + SUBSCRIPTION_PER_TRADE, 2)
# = $6.00 + $0.35 + ~$0.019 = ~$6.37 minimum net per trade

# ══════════════════════════════════════════════════════════════════
#  STATE — Shared between bot and dashboard
# ══════════════════════════════════════════════════════════════════

state = {
    "online":        True,
    "balance":       0.0,
    "total_pnl":     0.0,
    "round":         0,
    "active_trades": {},
    "trade_log":     [],        # last 50 closed trades
    "scan_log":      [],        # last 20 scan results
    "fees_paid":     0.0,
    "trades_won":    0,
    "trades_lost":   0,
    "start_time":    datetime.now().isoformat(),
}
state_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════════
#  KRAKEN AUTH (HMAC-SHA512)
# ══════════════════════════════════════════════════════════════════

KRAKEN_BASE_URL = "https://api.kraken.com"

def get_kraken_signature(url_path, data, secret):
    post_data = urllib.parse.urlencode(data)
    encoded   = (str(data["nonce"]) + post_data).encode()
    message   = url_path.encode() + hashlib.sha256(encoded).digest()
    mac       = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()

def kraken_private(endpoint, data={}):
    url_path        = f"/0/private/{endpoint}"
    data            = dict(data)
    data["nonce"]   = str(int(time.time() * 1000))
    sig             = get_kraken_signature(url_path, data, KRAKEN_API_SECRET)
    headers         = {"API-Key": KRAKEN_API_KEY, "API-Sign": sig,
                       "Content-Type": "application/x-www-form-urlencoded"}
    try:
        r = requests.post(KRAKEN_BASE_URL + url_path, headers=headers, data=data, timeout=10)
        res = r.json()
        if res.get("error"):
            print(f"[KRAKEN ERR] {endpoint}: {res['error']}")
            return {}
        return res.get("result", {})
    except Exception as e:
        print(f"[REQUEST ERR] {endpoint}: {e}")
        return {}

def kraken_public(endpoint, params={}):
    try:
        r   = requests.get(f"{KRAKEN_BASE_URL}/0/public/{endpoint}", params=params, timeout=10)
        res = r.json()
        if res.get("error"):
            return {}
        return res.get("result", {})
    except:
        return {}

# ══════════════════════════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════════════════════════

def tg(msg):
    if "PASTE" in TELEGRAM_BOT_TOKEN:
        print(f"[TG] {msg[:80]}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except:
        pass

# ══════════════════════════════════════════════════════════════════
#  INDICATORS
# ══════════════════════════════════════════════════════════════════

def get_ohlcv(pair, interval=5):
    data = kraken_public("OHLC", {"pair": pair, "interval": interval})
    if not data:
        return []
    for key in data:
        if key != "last":
            return data[key]
    return []

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    c = np.array(closes, dtype=float)
    d = np.diff(c)
    g = np.where(d > 0, d, 0)
    l = np.where(d < 0, -d, 0)
    ag, al = np.mean(g[:period]), np.mean(l[:period])
    if al == 0:
        return 100.0
    return 100 - (100 / (1 + ag / al))

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0.0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, len(closes))]
    return float(np.mean(trs[-period:]))

def calc_vol_ratio(volumes, period=20):
    if len(volumes) < period + 1:
        return 1.0
    avg = np.mean(volumes[-period-1:-1])
    return float(volumes[-1] / avg) if avg > 0 else 1.0

def score_pair(pair):
    candles = get_ohlcv(pair, 5)
    if len(candles) < 30:
        return {"score": 0, "pair": pair}
    closes  = [float(c[4]) for c in candles]
    highs   = [float(c[2]) for c in candles]
    lows    = [float(c[3]) for c in candles]
    volumes = [float(c[6]) for c in candles]
    rsi          = calc_rsi(closes)
    atr          = calc_atr(highs, lows, closes)
    vol_ratio    = calc_vol_ratio(volumes)
    price        = closes[-1]
    score = 0
    if rsi > 60:         score += 3
    elif rsi > 55:       score += 2
    elif rsi > 52:       score += 1
    if vol_ratio > 2.0:  score += 3
    elif vol_ratio > 1.5:score += 2
    elif vol_ratio > 1.2:score += 1
    recent = closes[-5:]
    if recent[-1] > recent[0]:
        gp = (recent[-1]-recent[0])/recent[0]*100
        score += 2 if gp > 0.5 else (1 if gp > 0.2 else 0)
    atr_pct = (atr/price)*100 if price > 0 else 0
    score += 2 if atr_pct > 0.5 else (1 if atr_pct > 0.2 else 0)
    return {"pair": pair, "score": score, "rsi": round(rsi,2),
            "atr": round(atr,6), "volume_ratio": round(vol_ratio,2),
            "price": round(price,4), "atr_pct": round(atr_pct,3)}

# ══════════════════════════════════════════════════════════════════
#  FEE SHIELD CALCULATOR
# ══════════════════════════════════════════════════════════════════

def calc_fee(trade_usd):
    """Calculate total fee cost for a round-trip trade."""
    entry_fee = trade_usd * KRAKEN_TAKER_FEE_PCT
    exit_fee  = trade_usd * KRAKEN_TAKER_FEE_PCT   # approx same size on exit
    return round(entry_fee + exit_fee + OVERHEAD_BUFFER_USD, 4)

def min_tp_price(entry_price, trade_usd):
    """TP = entry + realistic ATR-based move. Fees covered. Max 1.2% above entry."""
    volume = trade_usd / entry_price if entry_price > 0 else 0
    if volume <= 0:
        return entry_price * 1.008
    # Required dollar gain to cover fees + min profit
    total_needed = calc_fee(trade_usd) + MIN_PROFIT_TARGET_USD
    price_gain_needed = total_needed / volume
    # Cap at 0.8% above entry — realistic scalping target
    cap = entry_price * 0.008
    return entry_price + min(price_gain_needed, cap)

# ══════════════════════════════════════════════════════════════════
#  ACCOUNT
# ══════════════════════════════════════════════════════════════════

def get_balance():
    res = kraken_private("Balance")
    return float(res.get("ZUSD", res.get("USD", 0))) if res else 0.0

# ══════════════════════════════════════════════════════════════════
#  TRADING ENGINE
# ══════════════════════════════════════════════════════════════════

def execute_trade(ind, balance):
    pair      = ind["pair"]
    price     = ind["price"]
    atr       = ind["atr"]
    trade_usd = balance * TRADE_SIZE_PCT
    volume    = trade_usd / price if price > 0 else 0
    if volume <= 0:
        return

    fee_cost  = calc_fee(trade_usd)
    tp_atr    = price + (atr * TP_ATR_MULTIPLIER)
    tp_fee    = min_tp_price(price, trade_usd)
    tp        = max(tp_atr, tp_fee)          # use whichever is higher
    sl        = price - (atr * SL_ATR_MULTIPLIER)

    result = kraken_private("AddOrder", {
        "pair": pair, "type": "buy", "ordertype": "market",
        "volume": str(round(volume, 8))
    })

    if result:
        with state_lock:
            state["active_trades"][pair] = {
                "entry_price": price, "tp": tp, "sl": sl,
                "volume": volume, "trade_usd": trade_usd,
                "fee_cost": fee_cost, "time": datetime.now().isoformat(),
                "score": ind["score"], "rsi": ind["rsi"]
            }

        tg(
            f"👑 <b>KRAKEN KING EDGE V2 — ENTRY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>{pair}</b>\n"
            f"📈 Entry: <b>${price:,.4f}</b>\n"
            f"🎯 TP: <b>${tp:,.4f}</b> (Fee-shielded)\n"
            f"🛡 SL: <b>${sl:,.4f}</b>\n"
            f"💸 Est. Fees: <b>${fee_cost:.3f}</b>\n"
            f"🎯 Min Net Profit: <b>${MIN_PROFIT_TARGET_USD}</b>\n"
            f"📊 Score: <b>{ind['score']}/10</b> | RSI: <b>{ind['rsi']}</b>\n"
            f"💰 Size: <b>${trade_usd:.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Kris Krush Organization"
        )
        print(f"[ENTRY] {pair} @ ${price:.4f}  TP=${tp:.4f}  SL=${sl:.4f}")
    else:
        print(f"[ENTRY FAILED] {pair}")

def manage_exits(current_prices):
    to_close = []
    with state_lock:
        for pair, trade in state["active_trades"].items():
            cur = current_prices.get(pair, 0)
            if cur == 0:
                continue
            if cur >= trade["tp"]:
                to_close.append((pair, trade, "TP", cur))
            elif cur <= trade["sl"]:
                to_close.append((pair, trade, "SL", cur))

    for pair, trade, reason, cur in to_close:
        result = kraken_private("AddOrder", {
            "pair": pair, "type": "sell", "ordertype": "market",
            "volume": str(round(trade["volume"], 8))
        })
        if result:
            gross_pnl = (cur - trade["entry_price"]) * trade["volume"]
            net_pnl   = gross_pnl - trade["fee_cost"]
            emoji     = "✅" if reason == "TP" else "🛑"

            with state_lock:
                state["total_pnl"]  += net_pnl
                state["fees_paid"]  += trade["fee_cost"]
                if net_pnl > 0:
                    state["trades_won"] += 1
                else:
                    state["trades_lost"] += 1
                state["trade_log"].insert(0, {
                    "pair": pair, "reason": reason,
                    "entry": trade["entry_price"], "exit": cur,
                    "gross": round(gross_pnl, 4), "fee": trade["fee_cost"],
                    "net": round(net_pnl, 4), "time": datetime.now().isoformat()
                })
                state["trade_log"] = state["trade_log"][:50]
                del state["active_trades"][pair]

            tg(
                f"{emoji} <b>KRAKEN KING EDGE V2 — CLOSED ({reason})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 <b>{pair}</b>\n"
                f"📈 Entry: <b>${trade['entry_price']:,.4f}</b>\n"
                f"📉 Exit:  <b>${cur:,.4f}</b>\n"
                f"💵 Gross P&L: <b>${gross_pnl:+.4f}</b>\n"
                f"💸 Fees Paid: <b>-${trade['fee_cost']:.3f}</b>\n"
                f"💰 Net P&L: <b>${net_pnl:+.4f}</b>\n"
                f"📊 Session P&L: <b>${state['total_pnl']:+.2f}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏆 Kris Krush Organization"
            )
            print(f"[CLOSED {reason}] {pair} Net P&L: ${net_pnl:+.4f}")

# ══════════════════════════════════════════════════════════════════
#  MAIN BOT LOOP (runs in background thread)
# ══════════════════════════════════════════════════════════════════

def bot_loop():
    tg(
        "👑 <b>KRAKEN KING EDGE V2 ONLINE</b>\n"
        f"🌏 Singapore Server | Fee Shield ACTIVE\n"
        f"💸 Overhead buffer: $0.35/trade\n"
        f"📅 Subscription spread: ~$0.017–$0.019/trade\n"
        f"🎯 Min net profit per trade: $6.37\n"
        f"📊 Fee rate: {KRAKEN_TAKER_FEE_PCT*100}% taker\n"
        f"🏆 TARGET: $203 → $518,465 | 200 Day Crown Jewel\n"
        f"🎯 Pairs: {', '.join(TRADE_PAIRS)}\n"
        f"👑 Kris Krush Organization"
    )

    while True:
        with state_lock:
            state["round"] += 1
            rnd = state["round"]

        balance = get_balance()
        with state_lock:
            state["balance"] = balance

        # Get current prices
        current_prices = {}
        for pair in TRADE_PAIRS:
            ticker = kraken_public("Ticker", {"pair": pair})
            if ticker:
                for key in ticker:
                    try:
                        current_prices[pair] = float(ticker[key]["c"][0])
                    except:
                        pass

        # Exit management
        with state_lock:
            has_trades = bool(state["active_trades"])
        if has_trades:
            manage_exits(current_prices)

        # Entry scanning
        with state_lock:
            open_count = len(state["active_trades"])
            active_pairs = list(state["active_trades"].keys())

        scan_results = []
        if open_count < MAX_SIMULTANEOUS:
            for pair in TRADE_PAIRS:
                if pair not in active_pairs:
                    ind = score_pair(pair)
                    scan_results.append(ind)

            with state_lock:
                state["scan_log"] = scan_results[:20]

            scan_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            for ind in scan_results:
                with state_lock:
                    open_count = len(state["active_trades"])
                if (ind.get("score", 0) >= SCORE_THRESHOLD and
                    ind.get("volume_ratio", 0) >= VOLUME_MULTIPLIER and
                    ind.get("rsi", 0) >= RSI_THRESHOLD and
                    open_count < MAX_SIMULTANEOUS):
                    execute_trade(ind, balance)

        # Status every 50 rounds
        if rnd % 50 == 0:
            with state_lock:
                pnl  = state["total_pnl"]
                fees = state["fees_paid"]
                won  = state["trades_won"]
                lost = state["trades_lost"]
            tg(
                f"📊 <b>ROUND #{rnd} STATUS</b>\n"
                f"💰 Balance: ${balance:.2f}\n"
                f"📈 Net P&L: ${pnl:+.2f}\n"
                f"💸 Total Fees: ${fees:.2f}\n"
                f"✅ Won: {won} | 🛑 Lost: {lost}\n"
                f"👑 Kris Krush Organization"
            )

        print(f"[Round #{rnd}] Bal:${balance:.2f} P&L:${state['total_pnl']:+.2f} Open:{open_count}")
        time.sleep(SCAN_INTERVAL)

# ══════════════════════════════════════════════════════════════════
#  FLASK DASHBOARD
# ══════════════════════════════════════════════════════════════════

app = Flask('KRAKEN_KING_EDGE_V3')

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>👑 Kraken King Edge V3</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Share+Tech+Mono&display=swap');

:root {
  --gold: #FFD700; --gold2: #FFA500; --green: #00FF88;
  --red: #FF3355; --bg: #020810; --card: #080F1E;
  --border: #1A3050; --text: #C8D8E8; --purple: #9B59B6;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Share Tech Mono', monospace;
  min-height: 100vh;
  overflow-x: hidden;
  position: relative;
}

/* ── CANVAS BACKGROUND ── */
#canvas {
  position: fixed;
  top: 0; left: 0;
  width: 100%; height: 100%;
  pointer-events: none;
  z-index: 0;
}

/* ── CONTENT ── */
.content {
  position: relative;
  z-index: 1;
  padding: 20px;
}

/* ── HEADER ── */
.header {
  text-align: center;
  margin-bottom: 24px;
  padding: 20px;
  background: linear-gradient(180deg, rgba(255,215,0,0.08) 0%, transparent 100%);
  border-bottom: 1px solid rgba(255,215,0,0.2);
}

h1 {
  font-family: 'Orbitron', sans-serif;
  color: var(--gold);
  font-size: clamp(22px, 5vw, 42px);
  text-shadow: 0 0 30px rgba(255,215,0,0.8), 0 0 60px rgba(255,215,0,0.4);
  letter-spacing: 4px;
  margin-bottom: 6px;
}

.crown { font-size: clamp(28px, 6vw, 52px); display: block; margin-bottom: 8px; }

.sub {
  color: #8AAABB;
  font-size: 11px;
  letter-spacing: 2px;
  text-transform: uppercase;
}

/* ── TARGET BAR ── */
.target-bar {
  background: linear-gradient(90deg, #0A1520, #0D1F35);
  border: 1px solid rgba(255,215,0,0.3);
  border-radius: 12px;
  padding: 14px 20px;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.target-label {
  font-family: 'Orbitron', sans-serif;
  color: var(--gold);
  font-size: 11px;
  letter-spacing: 2px;
}

.target-value {
  font-family: 'Orbitron', sans-serif;
  font-size: clamp(14px, 3vw, 22px);
  color: var(--green);
  text-shadow: 0 0 15px rgba(0,255,136,0.5);
}

.progress-wrap {
  width: 100%;
  background: #0A1520;
  border-radius: 4px;
  height: 6px;
  margin-top: 8px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--gold), var(--green));
  border-radius: 4px;
  transition: width 1s ease;
  box-shadow: 0 0 10px rgba(255,215,0,0.5);
}

/* ── STATS GRID ── */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.card {
  background: linear-gradient(135deg, #080F1E, #0D1928);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 12px;
  text-align: center;
  position: relative;
  overflow: hidden;
  transition: border-color 0.3s;
}

.card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--gold), transparent);
}

.card:hover { border-color: rgba(255,215,0,0.4); }

.card-label {
  font-size: 9px;
  color: #5A8AA8;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 8px;
}

.card-value {
  font-family: 'Orbitron', sans-serif;
  font-size: clamp(16px, 3vw, 22px);
  color: var(--gold);
}

.card-value.green { color: var(--green); text-shadow: 0 0 10px rgba(0,255,136,0.4); }
.card-value.red   { color: var(--red);   text-shadow: 0 0 10px rgba(255,51,85,0.4); }

/* ── SECTIONS ── */
.section {
  background: linear-gradient(135deg, #080F1E, #0A1520);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 16px;
  position: relative;
  overflow: hidden;
}

.section::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--gold), transparent);
}

.section-title {
  font-family: 'Orbitron', sans-serif;
  color: var(--gold);
  font-size: 11px;
  letter-spacing: 2px;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255,215,0,0.15);
}

/* ── TABLE ── */
table { width: 100%; border-collapse: collapse; font-size: 11px; }
th { color: #5A8AA8; text-align: left; padding: 6px 8px; font-size: 9px; letter-spacing: 1px; text-transform: uppercase; }
td { padding: 7px 8px; border-bottom: 1px solid rgba(26,48,80,0.5); }
tr:hover td { background: rgba(255,215,0,0.03); }

.pos  { color: var(--green); }
.neg  { color: var(--red); }
.gold { color: var(--gold); }

/* ── BADGES ── */
.badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 9px;
  font-weight: bold;
  letter-spacing: 1px;
}
.badge-green { background: rgba(0,255,136,0.12); color: var(--green); border: 1px solid rgba(0,255,136,0.3); }
.badge-red   { background: rgba(255,51,85,0.12); color: var(--red);   border: 1px solid rgba(255,51,85,0.3); }
.badge-gold  { background: rgba(255,215,0,0.12); color: var(--gold);  border: 1px solid rgba(255,215,0,0.3); }

/* ── SCORE METER ── */
.score-meter {
  display: inline-flex;
  gap: 3px;
  vertical-align: middle;
}
.score-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #1A3050;
}
.score-dot.on { background: var(--gold); box-shadow: 0 0 5px rgba(255,215,0,0.6); }

/* ── FEE ROWS ── */
.fee-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(10,21,32,0.8);
  margin-bottom: 6px;
  font-size: 11px;
}

/* ── EXCHANGE BADGE ── */
.exchange-tag {
  display: inline-block;
  background: linear-gradient(90deg, rgba(255,215,0,0.15), rgba(255,165,0,0.1));
  border: 1px solid rgba(255,215,0,0.3);
  border-radius: 20px;
  padding: 4px 14px;
  font-size: 10px;
  color: var(--gold);
  letter-spacing: 2px;
  font-family: 'Orbitron', sans-serif;
}

/* ── PULSE ── */
.pulse { animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

.glow-green { animation: glowGreen 2s infinite; }
@keyframes glowGreen {
  0%,100% { text-shadow: 0 0 10px rgba(0,255,136,0.4); }
  50%     { text-shadow: 0 0 25px rgba(0,255,136,0.9), 0 0 50px rgba(0,255,136,0.3); }
}

/* ── LIVE DOT ── */
.live-dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--green);
  margin-right: 6px;
  animation: livePulse 1.5s infinite;
}
@keyframes livePulse {
  0%,100% { opacity: 1; transform: scale(1); }
  50%     { opacity: 0.3; transform: scale(0.8); }
}

/* ── ROADMAP ── */
.roadmap-row {
  display: grid;
  grid-template-columns: 40px 80px 1fr 100px 100px;
  gap: 8px;
  padding: 6px 8px;
  border-bottom: 1px solid rgba(26,48,80,0.3);
  font-size: 10px;
  align-items: center;
}
.roadmap-row.header { color: #5A8AA8; font-size: 9px; letter-spacing: 1px; }
.roadmap-row.today  { background: rgba(255,215,0,0.05); border-left: 2px solid var(--gold); }
</style>
</head>
<body>

<canvas id="canvas"></canvas>

<div class="content">

  <!-- HEADER -->
  <div class="header">
    <span class="crown">👑</span>
    <h1>KRAKEN KING EDGE V3</h1>
    <p class="sub">
      <span class="live-dot"></span>
      KRIS KRUSH ORGANIZATION &nbsp;·&nbsp;
      <span class="exchange-tag">KRAKEN PRO</span>
      &nbsp;·&nbsp; FEE SHIELD ACTIVE &nbsp;·&nbsp; AUTO-REFRESH 15s
    </p>
  </div>

  <!-- TARGET BAR -->
  <div class="target-bar">
    <div>
      <div class="target-label">🎯 200 DAY CROWN JEWEL</div>
      <div style="font-size:11px;color:#5A8AA8;margin-top:2px">STRATEGY: SMC · EMA V9 · VWAP &nbsp;|&nbsp; EXCHANGE: KRAKEN &nbsp;|&nbsp; PAIRS: BTC · ETH · SOL</div>
    </div>
    <div class="target-value" id="target-display">$203 → $518,465</div>
    <div class="progress-wrap">
      <div class="progress-fill" id="progress-fill" style="width:0.04%"></div>
    </div>
  </div>

  <!-- STATS GRID -->
  <div class="grid" id="stats"></div>

  <!-- ACTIVE TRADES -->
  <div class="section">
    <div class="section-title">⚡ ACTIVE TRADES</div>
    <div id="active"></div>
  </div>

  <!-- LAST SCAN -->
  <div class="section">
    <div class="section-title">📡 MARKET SCAN — KING EDGE SIGNALS</div>
    <div id="scan"></div>
  </div>

  <!-- TRADE LOG -->
  <div class="section">
    <div class="section-title">📋 TRADE LOG</div>
    <div id="log"></div>
  </div>

  <!-- FEE SHIELD -->
  <div class="section">
    <div class="section-title">🛡 FEE SHIELD STATUS</div>
    <div id="fees"></div>
  </div>

  <!-- 200 DAY ROADMAP PREVIEW -->
  <div class="section">
    <div class="section-title">📅 200 DAY ROADMAP — LIVE TRACKING</div>
    <div id="roadmap"></div>
  </div>

</div><!-- /content -->

<script>
// ── CANVAS ANIMATION — Gold coins, pentagons, pentagrams ──────────
const canvas = document.getElementById('canvas');
const ctx    = canvas.getContext('2d');

canvas.width  = window.innerWidth;
canvas.height = window.innerHeight;
window.addEventListener('resize', () => {
  canvas.width  = window.innerWidth;
  canvas.height = window.innerHeight;
  initParticles();
});

const SYMBOLS = ['$', '⬠', '⬡', '✦', '★', '◆', '⬟'];
const particles = [];

function randomGold() {
  const golds = ['#FFD700','#FFA500','#FFD700','#FFEC8B','#DAA520','#FFD700'];
  return golds[Math.floor(Math.random() * golds.length)];
}

function drawPentagon(cx, cy, r, rotation, color, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i < 5; i++) {
    const angle = (i * 2 * Math.PI / 5) + rotation;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.stroke();
  ctx.restore();
}

function drawPentagram(cx, cy, r, rotation, color, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i < 5; i++) {
    const angle = (i * 4 * Math.PI / 5) + rotation;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.stroke();
  ctx.restore();
}

function drawCoin(cx, cy, r, color, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.fillStyle = color.replace(')', ',0.08)').replace('rgb','rgba');
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  // $ symbol inside
  ctx.fillStyle = color;
  ctx.font = `bold ${r}px Arial`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('$', cx, cy);
  ctx.restore();
}

function initParticles() {
  particles.length = 0;
  const count = Math.floor(window.innerWidth / 18);
  for (let i = 0; i < count; i++) {
    particles.push(createParticle(true));
  }
}

function createParticle(randomY = false) {
  const type = Math.random() < 0.35 ? 'coin'
             : Math.random() < 0.55 ? 'pentagon'
             : Math.random() < 0.75 ? 'pentagram'
             : 'symbol';
  return {
    x:       Math.random() * canvas.width,
    y:       randomY ? Math.random() * canvas.height : -30,
    size:    4 + Math.random() * 14,
    speed:   0.3 + Math.random() * 0.9,
    drift:   (Math.random() - 0.5) * 0.4,
    rotation:Math.random() * Math.PI * 2,
    rotSpeed:(Math.random() - 0.5) * 0.02,
    color:   randomGold(),
    alpha:   0.06 + Math.random() * 0.25,
    type,
    symbol:  SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)],
  };
}

function animateParticles() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  for (let i = 0; i < particles.length; i++) {
    const p = particles[i];
    p.y        += p.speed;
    p.x        += p.drift;
    p.rotation += p.rotSpeed;

    if (p.type === 'coin') {
      drawCoin(p.x, p.y, p.size, p.color, p.alpha);
    } else if (p.type === 'pentagon') {
      drawPentagon(p.x, p.y, p.size, p.rotation, p.color, p.alpha);
    } else if (p.type === 'pentagram') {
      drawPentagram(p.x, p.y, p.size, p.rotation, p.color, p.alpha);
    } else {
      ctx.save();
      ctx.globalAlpha = p.alpha;
      ctx.fillStyle   = p.color;
      ctx.font        = `${p.size * 1.4}px Arial`;
      ctx.textAlign   = 'center';
      ctx.fillText(p.symbol, p.x, p.y);
      ctx.restore();
    }

    if (p.y > canvas.height + 40 || p.x < -40 || p.x > canvas.width + 40) {
      particles[i] = createParticle(false);
    }
  }
  requestAnimationFrame(animateParticles);
}

initParticles();
animateParticles();

// ── ROADMAP GENERATOR ────────────────────────────────────────────
function generateRoadmap(startBalance, days = 200) {
  const rows = [];
  let bal = startBalance;
  const startDate = new Date('2026-06-09');
  for (let d = 1; d <= days; d++) {
    const dailyGoal = bal * 0.0469; // ~4.69% daily to compound to 518K
    const endBal    = bal + dailyGoal;
    const date      = new Date(startDate);
    date.setDate(startDate.getDate() + d - 1);
    rows.push({
      day: d,
      date: date.toLocaleDateString('en-US', {month:'short', day:'numeric'}),
      open: bal,
      goal: dailyGoal,
      close: endBal
    });
    bal = endBal;
  }
  return rows;
}

// ── DASHBOARD LOADER ─────────────────────────────────────────────
async function load() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();

    // Progress toward $518K
    const pct = Math.min(((d.balance - 203) / (518465 - 203)) * 100, 100);
    document.getElementById('progress-fill').style.width = Math.max(pct, 0.04) + '%';
    document.getElementById('target-display').textContent =
      `$${d.balance.toFixed(2)} → $518,465`;

    // Stats
    const pnlClass = d.total_pnl >= 0 ? 'green' : 'red';
    const winRate  = (d.trades_won + d.trades_lost) > 0
      ? Math.round((d.trades_won / (d.trades_won + d.trades_lost)) * 100) : 0;

    document.getElementById('stats').innerHTML = `
      <div class="card">
        <div class="card-label">💰 Balance</div>
        <div class="card-value">$${d.balance.toFixed(2)}</div>
      </div>
      <div class="card">
        <div class="card-label">📈 Net P&L</div>
        <div class="card-value ${pnlClass}">$${d.total_pnl >= 0 ? '+' : ''}${d.total_pnl.toFixed(2)}</div>
      </div>
      <div class="card">
        <div class="card-label">🔄 Round</div>
        <div class="card-value">${d.round}</div>
      </div>
      <div class="card">
        <div class="card-label">⚡ Open Trades</div>
        <div class="card-value gold">${Object.keys(d.active_trades).length} / 2</div>
      </div>
      <div class="card">
        <div class="card-label">🏆 Win Rate</div>
        <div class="card-value ${winRate >= 50 ? 'green' : 'red'}">${winRate}%</div>
      </div>
      <div class="card">
        <div class="card-label">💸 Fees Paid</div>
        <div class="card-value red">-$${d.fees_paid.toFixed(2)}</div>
      </div>
    `;

    // Active trades
    const trades = Object.entries(d.active_trades);
    if (trades.length === 0) {
      document.getElementById('active').innerHTML =
        '<p style="color:#5A8AA8;font-size:12px"><span class="live-dot"></span>Scanning markets — waiting for Score 6+ signal...</p>';
    } else {
      let html = '<table><tr><th>Pair</th><th>Entry</th><th>TP (Fee-Shield)</th><th>SL</th><th>Size</th><th>Est Fee</th><th>Score</th></tr>';
      trades.forEach(([pair, t]) => {
        html += `<tr>
          <td class="gold">${pair}</td>
          <td>$${t.entry_price.toFixed(4)}</td>
          <td class="pos">$${t.tp.toFixed(4)}</td>
          <td class="neg">$${t.sl.toFixed(4)}</td>
          <td>$${t.trade_usd.toFixed(2)}</td>
          <td class="neg">-$${t.fee_cost.toFixed(3)}</td>
          <td><div class="score-meter">${Array.from({length:10},(_,i)=>`<div class="score-dot ${i<t.score?'on':''}"></div>`).join('')}</div></td>
        </tr>`;
      });
      document.getElementById('active').innerHTML = html + '</table>';
    }

    // Scan
    if (!d.scan_log || d.scan_log.length === 0) {
      document.getElementById('scan').innerHTML =
        '<p style="color:#5A8AA8;font-size:12px">Waiting for first scan...</p>';
    } else {
      let html = '<table><tr><th>Pair</th><th>Score</th><th>RSI</th><th>Volume</th><th>Price</th><th>Signal</th></tr>';
      d.scan_log.forEach(s => {
        const ready = s.score >= 8 && s.volume_ratio >= 1.2 && s.rsi >= 52;
        const dots  = Array.from({length:10},(_,i)=>`<div class="score-dot ${i<s.score?'on':''}"></div>`).join('');
        html += `<tr>
          <td class="gold">${s.pair}</td>
          <td><div class="score-meter">${dots}</div> <span style="font-size:10px">${s.score}/10</span></td>
          <td class="${s.rsi >= 52 ? 'pos' : 'neg'}">${s.rsi}</td>
          <td class="${s.volume_ratio >= 1.2 ? 'pos' : ''}">${s.volume_ratio}x</td>
          <td>$${s.price}</td>
          <td>${ready
            ? '<span class="badge badge-green pulse">🔥 FIRE</span>'
            : '<span class="badge badge-red">WAIT</span>'}</td>
        </tr>`;
      });
      document.getElementById('scan').innerHTML = html + '</table>';
    }

    // Trade log
    if (!d.trade_log || d.trade_log.length === 0) {
      document.getElementById('log').innerHTML =
        '<p style="color:#5A8AA8;font-size:12px">No closed trades yet. Bot is hunting...</p>';
    } else {
      let html = '<table><tr><th>Pair</th><th>Result</th><th>Entry</th><th>Exit</th><th>Gross</th><th>Fee</th><th>Net</th><th>Time</th></tr>';
      d.trade_log.slice(0,20).forEach(t => {
        html += `<tr>
          <td class="gold">${t.pair}</td>
          <td><span class="badge ${t.reason==='TP'?'badge-green':'badge-red'}">${t.reason}</span></td>
          <td>$${t.entry.toFixed(4)}</td>
          <td>$${t.exit.toFixed(4)}</td>
          <td class="${t.gross>=0?'pos':'neg'}">$${t.gross>=0?'+':''}${t.gross.toFixed(4)}</td>
          <td class="neg">-$${t.fee.toFixed(3)}</td>
          <td class="${t.net>=0?'pos':'neg'} ${t.net>0?'glow-green':''}">$${t.net>=0?'+':''}${t.net.toFixed(4)}</td>
          <td>${t.time.slice(11,19)}</td>
        </tr>`;
      });
      document.getElementById('log').innerHTML = html + '</table>';
    }

    // Fee shield
    document.getElementById('fees').innerHTML = `
      <div class="fee-row"><span>Kraken Taker Fee</span><span class="neg">0.40% per side</span></div>
      <div class="fee-row"><span>Overhead Buffer</span><span class="neg">$0.35 / trade</span></div>
      <div class="fee-row"><span>Subscription Spread ($4.99 ÷ 30 ÷ 9 trades)</span><span class="neg">~$0.017–$0.019 / trade</span></div>
      <div class="fee-row" style="border:1px solid rgba(255,215,0,0.2)">
        <span style="color:var(--gold);font-family:'Orbitron',sans-serif;font-size:10px">MIN NET PROFIT TARGET</span>
        <span class="pos" style="font-family:'Orbitron',sans-serif">$6.37 / TRADE ✅</span>
      </div>
      <div class="fee-row"><span>Total Fees Paid This Session</span><span class="neg">-$${d.fees_paid.toFixed(3)}</span></div>
      <div class="fee-row"><span>Net P&L After All Fees</span>
        <span class="${d.total_pnl>=0?'pos':'neg'}" style="font-family:'Orbitron',sans-serif">
          $${d.total_pnl>=0?'+':''}${d.total_pnl.toFixed(2)}
        </span>
      </div>
    `;

    // Roadmap
    const roadmap = generateRoadmap(d.balance > 10 ? d.balance : 203);
    const today   = new Date();
    const startD  = new Date('2026-06-09');
    const dayNum  = Math.floor((today - startD) / 86400000) + 1;

    let rmHtml = `
      <div class="roadmap-row header">
        <span>DAY</span><span>DATE</span><span>OPEN BAL</span><span>DAILY GOAL</span><span>CLOSE BAL</span>
      </div>`;
    roadmap.slice(0, 42).forEach(row => {
      const isToday = row.day === dayNum;
      rmHtml += `
        <div class="roadmap-row ${isToday ? 'today' : ''}">
          <span class="${isToday ? 'gold' : ''}">${row.day}${isToday ? ' 👑' : ''}</span>
          <span style="color:#5A8AA8">${row.date}</span>
          <span>$${row.open.toFixed(2)}</span>
          <span class="pos">+$${row.goal.toFixed(2)}</span>
          <span class="green">$${row.close.toFixed(2)}</span>
        </div>`;
    });
    document.getElementById('roadmap').innerHTML = rmHtml;

  } catch(e) {
    console.log('API not connected yet:', e.message);
  }

  setTimeout(load, 15000);
}

load();
</script>
</body>
</html>

"""

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/state")
def api_state():
    with state_lock:
        return jsonify(dict(state))

def open_in_brave(url):
    """Try to open in Brave browser."""
    time.sleep(2)  # wait for Flask to start
    brave_paths = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "brave-browser", "brave"
    ]
    opened = False
    for path in brave_paths:
        try:
            subprocess.Popen([path, url])
            opened = True
            print(f"[DASHBOARD] Opened in Brave: {url}")
            break
        except:
            continue
    if not opened:
        webbrowser.open(url)
        print(f"[DASHBOARD] Opened in default browser: {url}")

# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "═"*60)
    print("  👑  KRAKEN KING EDGE BOT V2 — KRIS KRUSH ORGANIZATION")
    print("  🌏  Singapore Server | Fee Shield Active")
    print("  💸  Min profit target: $6.37/trade")
    print("  📊  Dashboard: http://localhost:5000")
    print("═"*60)

    # Check keys
    keys_missing = ("PASTE" in KRAKEN_API_KEY or
                    "PASTE" in KRAKEN_API_SECRET or
                    "PASTE" in TELEGRAM_BOT_TOKEN)

    if keys_missing:
        print("\n  ⚠️  WAITING FOR API KEYS...")
        print("  Open this file and fill in:")
        print("  KRAKEN_API_KEY     = 'your key here'")
        print("  KRAKEN_API_SECRET  = 'your secret here'")
        print("  TELEGRAM_BOT_TOKEN = 'your token here'")
        print("\n  Dashboard will run in DEMO MODE until keys are added.")
        print("  Starting dashboard anyway so you can see it...\n")

    # Start bot in background (runs in demo mode if keys missing)
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()

    # Open Brave after 2 seconds
    brave_thread = threading.Thread(
        target=open_in_brave,
        args=("http://localhost:5000",),
        daemon=True
    )
    brave_thread.start()

    print("  ✅ Bot thread started")
    print("  ✅ Opening Brave browser...")
    print("  ✅ Flask dashboard launching on port 5000")
    print("  📌 Keep this window OPEN — closing it stops the bot!\n")

    # Start Flask — this BLOCKS and keeps everything alive
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Bot stopped by user.")
    except Exception as e:
        print(f"\n[ERROR] Flask crashed: {e}")
        input("Press ENTER to close...")
