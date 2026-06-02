"""
👑 KING SNIPER V7 — KRIS KRUSH
NO PYGAME — Opens in your browser automatically
Works on Python 3.11, 3.12, 3.13, 3.14 — ANY version
Requirements: pip install requests flask
"""

import requests
import threading
import time
import webbrowser
from datetime import datetime
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# ================== YOUR TELEGRAM KEYS ==================
TELEGRAM_TOKEN   = "8760736306:AAG8Ni_0ljenI6KWBWT5m0zK8W67e_uYJF8"
TELEGRAM_CHAT_ID = "1295412342"
TELEGRAM_ENABLED = True

# ================== CONFIG ==================
MIN_MCAP  =  3_000
MAX_MCAP  = 150_000
MIN_LIQ   =  1_000
SCAN_SECS =     15
TARGET_X  =    120

# ================== STATE ==================
hot_targets  = []
log_msgs     = []
scan_count   = 0
last_scan    = "Never"
alerts_sent  = 0

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    log_msgs.insert(0, f"[{ts}] {msg}")
    if len(log_msgs) > 50: log_msgs.pop()

def tg(msg):
    global alerts_sent
    if not TELEGRAM_ENABLED: return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=5
        )
        alerts_sent += 1
    except: pass

def score_token(p):
    s = 0
    mcap  = float(p.get("marketCap", 0) or 0)
    liq   = float(p.get("liquidity", {}).get("usd", 0) or 0)
    v5m   = float(p.get("volume", {}).get("m5", 0) or 0)
    ch5m  = float(p.get("priceChange", {}).get("m5", 0) or 0)
    ch1h  = float(p.get("priceChange", {}).get("h1", 0) or 0)
    buys5 = int(p.get("txns", {}).get("m5", {}).get("buys", 0) or 0)
    sells5= int(p.get("txns", {}).get("m5", {}).get("sells", 0) or 0)
    buys1 = int(p.get("txns", {}).get("h1", {}).get("buys", 0) or 0)
    sells1= int(p.get("txns", {}).get("h1", {}).get("sells", 0) or 0)

    if 10000 <= mcap <= 25000:  s += 35
    elif 5000 <= mcap <= 50000: s += 20
    elif mcap <= 75000:         s += 10
    if ch5m > 50:  s += 30
    elif ch5m > 20: s += 20
    elif ch5m > 10: s += 12
    elif ch5m > 5:  s += 6
    if ch1h > 200: s += 25
    elif ch1h > 100: s += 18
    elif ch1h > 50: s += 10
    if v5m > 5000:  s += 20
    elif v5m > 2000: s += 12
    elif v5m > 500:  s += 6
    t5 = buys5 + sells5
    if t5 > 0:
        if buys5/t5 > 0.80: s += 20
        elif buys5/t5 > 0.65: s += 10
        if sells5/t5 > 0.70: s -= 20
    if liq > 20000: s += 10
    elif liq > 8000: s += 5
    if liq < 3000: s -= 30
    t1 = buys1 + sells1
    if t1 > 0 and sells1/t1 > 0.65: s -= 15
    return max(0, min(100, s))

def fetch_pairs_from_url(url, headers):
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200: return []
        data = r.json()
        if isinstance(data, list):
            pairs = []
            for item in data[:15]:
                addr = item.get("tokenAddress", "")
                if addr:
                    try:
                        pr = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}", headers=headers, timeout=6)
                        if pr.status_code == 200:
                            pairs += [p for p in pr.json().get("pairs", []) if p.get("chainId") == "solana"]
                    except: pass
            return pairs
        return [p for p in data.get("pairs", []) if p.get("chainId") == "solana"]
    except: return []

def run_scan():
    global hot_targets, scan_count, last_scan
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        endpoints = [
            "https://api.dexscreener.com/latest/dex/search?q=pump+solana",
            "https://api.dexscreener.com/latest/dex/search?q=meme+sol",
            "https://api.dexscreener.com/latest/dex/search?q=new+solana",
            "https://api.dexscreener.com/token-profiles/latest/v1",
        ]
        all_pairs = []
        for url in endpoints:
            all_pairs.extend(fetch_pairs_from_url(url, headers))
        seen = set()
        pairs = []
        for p in all_pairs:
            addr = p.get("pairAddress", "")
            if addr and addr not in seen:
                seen.add(addr)
                pairs.append(p)
        results = []
        for p in pairs:
            mcap = float(p.get("marketCap", 0) or 0)
            liq  = float(p.get("liquidity", {}).get("usd", 0) or 0)
            v5m  = float(p.get("volume", {}).get("m5", 0) or 0)
            buys5= int(p.get("txns", {}).get("m5", {}).get("buys", 0) or 0)
            if not (MIN_MCAP <= mcap <= MAX_MCAP): continue
            if liq < MIN_LIQ: continue
            sc = score_token(p)
            results.append((sc, p))
        results.sort(key=lambda x: x[0], reverse=True)
        hot_targets = results[:15]
        scan_count += 1
        last_scan = datetime.now().strftime("%H:%M:%S")
        found = len(results)
        hot = sum(1 for s,_ in results if s >= 70)
        log(f"Scan #{scan_count}: {found} targets, {hot} 🔥 HOT")
        if results and results[0][0] >= 70:
            sc, p = results[0]
            sym  = p.get("baseToken", {}).get("symbol", "???")
            mcap = float(p.get("marketCap", 0) or 0)
            ch5m = float(p.get("priceChange", {}).get("m5", 0) or 0)
            url  = p.get("url", "")
            log(f"🔥 HOT SNIPE: ${sym} score {sc}/100 mcap ${mcap:,.0f}")
            tg(f"👑 KING SNIPER V7 — KRIS KRUSH\n🔥 Score {sc}/100\n${sym} mcap ${mcap:,.0f}\n5min: +{ch5m:.1f}%\n120X = ${mcap*120:,.0f}\n{url}")
    except Exception as e:
        log(f"[ERR] {str(e)[:60]}")

def bg_scan():
    while True:
        run_scan()
        time.sleep(SCAN_SECS)

# ================== WEB DASHBOARD ==================
HTML = """
<!DOCTYPE html>
<html>
<head>
<title>👑 KING SNIPER V7 — KRIS KRUSH</title>
<meta http-equiv="refresh" content="15">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#06030F; color:#fff; font-family:Arial,sans-serif; padding:10px; }
.header { background:#0F061E; border-bottom:2px solid gold; padding:12px; text-align:center; margin-bottom:10px; border-radius:8px; }
.title { color:gold; font-size:26px; font-weight:bold; }
.sub { color:#FF64B4; font-size:13px; margin-top:4px; }
.stats { display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap; }
.stat { background:#14082A; border:1px solid #6600CC; border-radius:8px; padding:8px 14px; flex:1; min-width:120px; text-align:center; }
.stat-label { color:#666; font-size:11px; }
.stat-val { font-size:18px; font-weight:bold; margin-top:2px; }
.grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.panel { background:#14082A; border:1px solid #6600CC; border-radius:10px; padding:10px; }
.panel-title { color:#AA00FF; font-size:14px; font-weight:bold; margin-bottom:8px; border-bottom:1px solid #330055; padding-bottom:6px; }
.token-row { display:flex; align-items:center; gap:8px; padding:7px 6px; border-radius:6px; margin-bottom:4px; cursor:pointer; border:1px solid transparent; }
.token-row:hover { border-color:#6600CC; background:#1E0A35; }
.badge { border-radius:5px; padding:3px 7px; font-size:12px; font-weight:bold; min-width:36px; text-align:center; }
.hot  { background:#003020; color:#00FF82; border:1px solid #00FF82; }
.warm { background:#3A2000; color:#FFA500; border:1px solid #FFA500; }
.cool { background:#1A1A2A; color:#666; border:1px solid #444; }
.sweet { background:#003020; color:#00FF82; border:1px solid #00FF82; font-size:11px; padding:2px 5px; border-radius:4px; }
.green { color:#00FF82; }
.red   { color:#FF3C64; }
.cyan  { color:#00D2FF; }
.gold  { color:gold; }
.gray  { color:#666; }
.detail { font-size:13px; }
.detail-row { display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid #1A0A2A; }
.dex-link { background:#002040; border:1px solid #00D2FF; border-radius:6px; padding:6px 10px; margin-top:8px; font-size:11px; color:#00D2FF; word-break:break-all; }
.log-entry { font-size:12px; color:#666; padding:3px 0; border-bottom:1px solid #0A0515; }
.log-entry.hot-log { color:#00FF82; }
.log-entry.err-log { color:#FF3C64; }
.mission { background:#14082A; border:1px solid gold; border-radius:10px; padding:10px; margin-bottom:10px; }
.mission-title { color:gold; font-size:14px; font-weight:bold; margin-bottom:8px; }
.milestones { display:flex; gap:6px; flex-wrap:wrap; }
.milestone { background:#0A0515; border-radius:6px; padding:6px 10px; text-align:center; font-size:12px; border:1px solid #333; }
.refresh { color:#444; font-size:11px; text-align:right; margin-top:4px; }
@media(max-width:700px){ .grid{grid-template-columns:1fr;} }
</style>
</head>
<body>
<div class="header">
  <div class="title">👑 KING SNIPER V7 — KRIS KRUSH</div>
  <div class="sub">$15K Market Cap Hunter &nbsp;•&nbsp; 120X Mission &nbsp;•&nbsp; Solana &nbsp;•&nbsp; DexScreener Live</div>
</div>

<div class="stats" id="stats">Loading stats...</div>

<div class="mission">
  <div class="mission-title">🎯 120X MISSION MAP — Entry $15K → Target $1.8M mcap</div>
  <div class="milestones">
    <div class="milestone"><span class="green">Entry</span><br>$15K</div>
    <div class="milestone"><span class="cyan">2x</span><br>$30K</div>
    <div class="milestone"><span class="cyan">5x</span><br>$75K</div>
    <div class="milestone"><span class="gold">10x</span><br>$150K</div>
    <div class="milestone" style="border-color:orange"><span style="color:orange">25x</span><br>$375K</div>
    <div class="milestone" style="border-color:red"><span class="red">50x</span><br>$750K</div>
    <div class="milestone" style="border-color:gold"><span class="gold">120x 👑</span><br>$1.8M</div>
  </div>
</div>

<div class="grid">
  <div class="panel">
    <div class="panel-title">🔥 $15K ZONE TARGETS</div>
    <div id="token-list">Loading...</div>
  </div>
  <div class="panel">
    <div class="panel-title">⚡ TOP SNIPE DETAIL</div>
    <div id="token-detail">Select a token...</div>
  </div>
</div>

<div class="panel" style="margin-top:10px">
  <div class="panel-title">📋 ACTIVITY LOG</div>
  <div id="log-panel">Loading...</div>
</div>

<div class="refresh">Auto-refreshes every 15 seconds</div>

<script>
let selectedIdx = 0;
let tokens = [];

async function loadData() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();
    tokens = d.tokens || [];
    renderStats(d);
    renderTokens(tokens);
    renderDetail(tokens[selectedIdx]);
    renderLog(d.log);
  } catch(e) { console.error(e); }
}

function renderStats(d) {
  document.getElementById('stats').innerHTML = `
    <div class="stat"><div class="stat-label">SCANS</div><div class="stat-val cyan">${d.scan_count}</div></div>
    <div class="stat"><div class="stat-label">🔥 TARGETS</div><div class="stat-val green">${d.token_count}</div></div>
    <div class="stat"><div class="stat-label">ALERTS SENT</div><div class="stat-val" style="color:orange">${d.alerts_sent}</div></div>
    <div class="stat"><div class="stat-label">LAST SCAN</div><div class="stat-val gray">${d.last_scan}</div></div>
    <div class="stat"><div class="stat-label">TELEGRAM</div><div class="stat-val" style="color:${d.telegram ? '#00FF82' : '#FF3C64'}">${d.telegram ? 'ON' : 'OFF'}</div></div>
    <div class="stat"><div class="stat-label">ZONE</div><div class="stat-val gold">$5K–$75K</div></div>
  `;
}

function renderTokens(tokens) {
  if (!tokens.length) {
    document.getElementById('token-list').innerHTML = '<div class="gray">Scanning... please wait</div>';
    return;
  }
  let html = '';
  tokens.forEach((t, i) => {
    const sc = t.score;
    const badgeClass = sc >= 70 ? 'hot' : sc >= 50 ? 'warm' : 'cool';
    const ch5 = t.ch5m >= 0 ? `<span class="green">+${t.ch5m.toFixed(1)}%</span>` : `<span class="red">${t.ch5m.toFixed(1)}%</span>`;
    const sweet = (t.mcap >= 10000 && t.mcap <= 25000) ? '<span class="sweet">15K✓</span>' : '';
    html += `<div class="token-row" onclick="selectToken(${i})" style="${i===selectedIdx?'background:#1E0A35;border-color:#AA00FF':''}">
      <span class="badge ${badgeClass}">${sc}</span>
      ${sweet}
      <span style="font-weight:bold">$${t.symbol}</span>
      <span style="margin-left:auto">${ch5}</span>
      <span class="cyan" style="font-size:12px">$${formatNum(t.mcap)}</span>
      <span class="gold" style="font-size:11px">${t.target_x}x</span>
    </div>`;
  });
  document.getElementById('token-list').innerHTML = html;
}

function selectToken(i) {
  selectedIdx = i;
  renderTokens(tokens);
  renderDetail(tokens[i]);
}

function renderDetail(t) {
  if (!t) return;
  const rating = t.score >= 70 ? '🔥 SNIPE IT' : t.score >= 50 ? '⚡ WATCH' : '👀 MONITOR';
  const rc = t.score >= 70 ? '#00FF82' : t.score >= 50 ? 'orange' : '#666';
  document.getElementById('token-detail').innerHTML = `
    <div style="text-align:center;color:${rc};font-size:18px;font-weight:bold;margin-bottom:10px">${rating}</div>
    <div class="detail">
      <div class="detail-row"><span class="gray">Name</span><span class="gold">$${t.symbol} — ${t.name}</span></div>
      <div class="detail-row"><span class="gray">Price</span><span>$${t.price}</span></div>
      <div class="detail-row"><span class="gray">Market Cap</span><span class="${(t.mcap>=5000&&t.mcap<=75000)?'green':'cyan'}">$${formatNum(t.mcap)} ${(t.mcap>=10000&&t.mcap<=25000)?'✓ SWEET SPOT':''}</span></div>
      <div class="detail-row"><span class="gray">Liquidity</span><span class="cyan">$${formatNum(t.liq)}</span></div>
      <div class="detail-row"><span class="gray">Vol 5min</span><span class="cyan">$${formatNum(t.v5m)}</span></div>
      <div class="detail-row"><span class="gray">Vol 1hr</span><span class="cyan">$${formatNum(t.v1h)}</span></div>
      <div class="detail-row"><span class="gray">5min</span><span class="${t.ch5m>=0?'green':'red'}">${t.ch5m>=0?'+':''}${t.ch5m.toFixed(2)}%</span></div>
      <div class="detail-row"><span class="gray">1hr</span><span class="${t.ch1h>=0?'green':'red'}">${t.ch1h>=0?'+':''}${t.ch1h.toFixed(2)}%</span></div>
      <div class="detail-row"><span class="gray">Buys/Sells 5m</span><span class="${t.buys5>t.sells5?'green':'red'}">${t.buys5} / ${t.sells5}</span></div>
      <div class="detail-row"><span class="gray">Score</span><span style="color:${rc};font-weight:bold">${t.score} / 100</span></div>
      <div class="detail-row"><span class="gray">120X needs</span><span class="gold">$${formatNum(t.mcap*120)} mcap</span></div>
    </div>
    <div class="dex-link">🔗 <a href="${t.url}" target="_blank" style="color:#00D2FF">${t.url}</a></div>
  `;
}

function renderLog(logs) {
  if (!logs || !logs.length) return;
  document.getElementById('log-panel').innerHTML = logs.slice(0,12).map(l => {
    const cls = l.includes('🔥')||l.includes('✅') ? 'hot-log' : l.includes('ERR') ? 'err-log' : '';
    return `<div class="log-entry ${cls}">${l}</div>`;
  }).join('');
}

function formatNum(n) {
  if (n >= 1000000) return (n/1000000).toFixed(2)+'M';
  if (n >= 1000) return (n/1000).toFixed(1)+'K';
  return n.toFixed(0);
}

loadData();
setInterval(loadData, 15000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/data")
def api_data():
    tokens = []
    for sc, p in hot_targets:
        sym   = p.get("baseToken", {}).get("symbol", "???")
        name  = p.get("baseToken", {}).get("name", "?")[:20]
        price = p.get("priceUsd", "0")
        mcap  = float(p.get("marketCap", 0) or 0)
        liq   = float(p.get("liquidity", {}).get("usd", 0) or 0)
        v5m   = float(p.get("volume", {}).get("m5", 0) or 0)
        v1h   = float(p.get("volume", {}).get("h1", 0) or 0)
        ch5m  = float(p.get("priceChange", {}).get("m5", 0) or 0)
        ch1h  = float(p.get("priceChange", {}).get("h1", 0) or 0)
        buys5 = int(p.get("txns", {}).get("m5", {}).get("buys", 0) or 0)
        sells5= int(p.get("txns", {}).get("m5", {}).get("sells", 0) or 0)
        url   = p.get("url", "")
        tx = round(TARGET_X * 15000 / mcap) if mcap > 0 else 0
        tokens.append({
            "score": sc, "symbol": sym, "name": name, "price": price,
            "mcap": mcap, "liq": liq, "v5m": v5m, "v1h": v1h,
            "ch5m": ch5m, "ch1h": ch1h, "buys5": buys5, "sells5": sells5,
            "url": url, "target_x": tx
        })
    return jsonify({
        "tokens": tokens,
        "scan_count": scan_count,
        "token_count": len(tokens),
        "alerts_sent": alerts_sent,
        "last_scan": last_scan,
        "telegram": TELEGRAM_ENABLED,
        "log": log_msgs[:20]
    })

if __name__ == "__main__":
    log("👑 King Sniper V7 started — Welcome Kris Krush!")
    log("🎯 $15K mcap hunter active — scanning every 15s")
    tg("👑 KING SNIPER V7 ONLINE\nKris Krush — 120X Mission\nOpening dashboard in browser...")
    t = threading.Thread(target=bg_scan, daemon=True)
    t.start()
    time.sleep(2)
    webbrowser.open("http://localhost:5000")
    print("\n👑 KING SNIPER V7 RUNNING")
    print("📊 Dashboard: http://localhost:5000")
    print("Press CTRL+C to stop\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
