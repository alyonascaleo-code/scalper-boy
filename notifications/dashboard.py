import logging
from collections import deque
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string
from config import DASHBOARD_HOST, DASHBOARD_PORT

logger = logging.getLogger(__name__)

app = Flask(__name__)

_signals: deque = deque(maxlen=100)
_stats = {
    "total":   0,
    "long":    0,
    "short":   0,
    "started": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
}

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
<title>Crypto Scalping Bot</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0d1117; color:#e6edf3; font-family:'Segoe UI',monospace; }

  header { background:#161b22; padding:14px 24px; border-bottom:1px solid #30363d;
           display:flex; justify-content:space-between; align-items:center; }
  header h1 { font-size:1.3rem; color:#58a6ff; }
  .live-badge { background:#238636; padding:3px 10px; border-radius:20px;
                font-size:0.72rem; color:#fff; }

  /* ── Табы ── */
  .tabs-wrap { background:#161b22; border-bottom:1px solid #30363d;
               padding:0 24px; display:flex; gap:4px; overflow-x:auto; flex-wrap:nowrap; }
  .tab { padding:10px 16px; font-size:0.82rem; font-weight:600; cursor:pointer;
         border:none; background:transparent; color:#8b949e;
         border-bottom:2px solid transparent; white-space:nowrap; transition:.15s; }
  .tab:hover  { color:#e6edf3; }
  .tab.active { color:#58a6ff; border-bottom-color:#58a6ff; }
  .tab .cnt   { background:#21262d; border-radius:10px; padding:1px 6px;
                font-size:0.68rem; margin-left:5px; }
  .tab.active .cnt { background:#1f3a5f; color:#58a6ff; }

  /* ── Общие карточки ── */
  .section { padding:16px 24px 0; }
  .section-title { font-size:0.75rem; color:#8b949e; text-transform:uppercase;
                   letter-spacing:.08em; margin-bottom:10px; }
  .cards { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:16px; }
  .card { background:#161b22; border:1px solid #30363d; border-radius:8px;
          padding:13px 18px; min-width:110px; }
  .card .lbl { font-size:0.68rem; color:#8b949e; margin-bottom:3px; }
  .card .val { font-size:1.45rem; font-weight:700; }
  .c-blue  { color:#58a6ff; }
  .c-green { color:#3fb950; }
  .c-red   { color:#f85149; }
  .c-gold  { color:#d29922; }
  .c-grey  { color:#8b949e; font-size:.85rem!important; padding-top:5px; }

  /* ── Win Rate ── */
  .wr-wrap { background:#161b22; border:1px solid #30363d; border-radius:8px;
             padding:16px 22px; display:flex; align-items:center; gap:20px; margin-bottom:14px; }
  .wr-num  { font-size:2.8rem; font-weight:800; line-height:1; }
  .wr-info { flex:1; }
  .wr-info p { font-size:0.78rem; color:#8b949e; margin-bottom:6px; }
  .bar  { background:#21262d; border-radius:4px; height:7px; }
  .bar-fill { height:100%; border-radius:4px; transition:width .4s; }

  /* ── Таблица результатов ── */
  .tbl { width:100%; border-collapse:collapse; font-size:0.81rem; margin-bottom:20px; }
  .tbl th { background:#161b22; color:#8b949e; padding:8px 12px; text-align:left;
            border-bottom:1px solid #30363d; white-space:nowrap; }
  .tbl td { padding:7px 12px; border-bottom:1px solid #1c2128; }
  .tbl tr:hover td { background:#161b22; }
  .b-tp2  { background:#1f6feb; color:#fff; padding:2px 8px; border-radius:12px; font-size:.68rem; }
  .b-tp1  { background:#238636; color:#fff; padding:2px 8px; border-radius:12px; font-size:.68rem; }
  .b-sl   { background:#da3633; color:#fff; padding:2px 8px; border-radius:12px; font-size:.68rem; }
  .b-pend { background:#21262d; color:#8b949e; padding:2px 8px; border-radius:12px; font-size:.68rem; }
  .b-tout { background:#2d1f00; color:#d29922; padding:2px 8px; border-radius:12px; font-size:.68rem; }

  /* ── Сигналы ── */
  .sig-card { background:#161b22; border:1px solid #30363d; border-radius:8px;
              padding:14px; margin-bottom:10px; }
  .sig-card.long-card  { border-left:3px solid #3fb950; }
  .sig-card.short-card { border-left:3px solid #f85149; }
  .sig-head { display:flex; justify-content:space-between; margin-bottom:9px; }
  .sig-sym  { font-size:1.05rem; font-weight:700; }
  .sig-ts   { font-size:0.72rem; color:#8b949e; }
  .sig-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:9px; margin-bottom:9px; }
  .sig-item .lbl { font-size:.67rem; color:#8b949e; }
  .sig-item .val { font-size:.92rem; font-weight:600; }
  .conf-bar  { background:#21262d; border-radius:4px; height:5px; margin-top:7px; }
  .conf-fill { height:100%; border-radius:4px; background:#3fb950; }
  .reasons   { font-size:.72rem; color:#8b949e; margin-top:7px; line-height:1.6; }
  .no-data   { text-align:center; padding:40px; color:#8b949e; font-size:.88rem; }

  .hidden { display:none !important; }
</style>
</head>
<body>

<header>
  <h1>🤖 Crypto Scalping Bot</h1>
  <span class="live-badge">● LIVE</span>
</header>

<!-- ── ТАБЫ ── -->
<div class="tabs-wrap" id="tabs">
  <button class="tab active" data-coin="ALL" onclick="filterCoin('ALL')">
    Все <span class="cnt" id="cnt-ALL">{{ perf.total }}</span>
  </button>
  {% for coin in all_coins %}
  <button class="tab" data-coin="{{ coin }}" onclick="filterCoin('{{ coin }}')">
    {{ coin.replace('USDT','') }}
    <span class="cnt" id="cnt-{{ coin }}">{{ coin_counts[coin] }}</span>
  </button>
  {% endfor %}
</div>

<!-- ── АКТИВНОСТЬ ── -->
<div class="section">
  <div class="section-title">Активность</div>
  <div class="cards">
    <div class="card"><div class="lbl">Всего сигналов</div>
      <div class="val c-blue" id="stat-total">{{ stats.total }}</div></div>
    <div class="card"><div class="lbl">LONG</div>
      <div class="val c-green" id="stat-long">{{ stats.long }}</div></div>
    <div class="card"><div class="lbl">SHORT</div>
      <div class="val c-red" id="stat-short">{{ stats.short }}</div></div>
    <div class="card"><div class="lbl">Запущен</div>
      <div class="val c-grey">{{ stats.started }}</div></div>
  </div>
</div>

<!-- ── ТОЧНОСТЬ ── -->
<div class="section">
  <div class="section-title">📊 Точность (мониторинг 2ч на сигнал)</div>

  <div class="wr-wrap">
    <div class="wr-num" id="wr-pct" style="color:#3fb950">{{ perf.win_rate }}%</div>
    <div class="wr-info">
      <p id="wr-label">Win Rate по <b id="wr-resolved">{{ perf.resolved }}</b> завершённым сигналам</p>
      <div class="bar"><div class="bar-fill" id="wr-bar"
        style="width:{{ perf.win_rate }}%; background:#3fb950"></div></div>
    </div>
  </div>

  <div class="cards">
    <div class="card"><div class="lbl">🏆 TP2</div>
      <div class="val c-blue"  id="s-tp2">{{ perf.tp2 }}</div></div>
    <div class="card"><div class="lbl">✅ TP1</div>
      <div class="val c-green" id="s-tp1">{{ perf.tp1 }}</div></div>
    <div class="card"><div class="lbl">❌ Стоп</div>
      <div class="val c-red"   id="s-sl">{{ perf.sl }}</div></div>
    <div class="card"><div class="lbl">⏳ Ожидаем</div>
      <div class="val c-blue"  id="s-pend">{{ perf.pending }}</div></div>
    <div class="card"><div class="lbl">⌛ Таймаут</div>
      <div class="val c-gold"  id="s-tout">{{ perf.timeout }}</div></div>
  </div>

  <!-- Таблица результатов -->
  <table class="tbl" id="tracker-table">
    <thead>
      <tr>
        <th>Монета</th><th>Направление</th><th>Увер.</th>
        <th>Вход</th><th>TP1 / TP2</th><th>Стоп</th>
        <th>Результат</th><th>Время</th>
      </tr>
    </thead>
    <tbody id="tracker-body">
      {% for r in perf.recent %}
      <tr class="trow" data-coin="{{ r.symbol }}" data-status="{{ r.status }}"
          data-tp1="{{ r.tp1 }}" data-tp2="{{ r.tp2 }}" data-sl="{{ r.stop_loss }}"
          data-dir="{{ r.direction }}" data-conf="{{ r.confidence }}">
        <td><b>{{ r.symbol }}</b></td>
        <td style="color:{% if r.direction=='LONG' %}#3fb950{% else %}#f85149{% endif %}">
          {{ '🟢' if r.direction=='LONG' else '🔴' }} {{ r.direction }}</td>
        <td>{{ r.confidence }}%</td>
        <td>{{ r.entry }}</td>
        <td style="color:#3fb950">{{ r.tp1 }} / {{ r.tp2 }}</td>
        <td style="color:#f85149">{{ r.stop_loss }}</td>
        <td>
          {% if r.status=='tp2' %}<span class="b-tp2">🏆 TP2</span>
          {% elif r.status=='tp1' %}<span class="b-tp1">✅ TP1</span>
          {% elif r.status=='sl' %}<span class="b-sl">❌ SL</span>
          {% elif r.status=='timeout' %}<span class="b-tout">⌛ 2ч</span>
          {% else %}<span class="b-pend">⏳ ждём</span>{% endif %}
        </td>
        <td style="color:#8b949e;font-size:.72rem">{{ r.sent_at }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% if not perf.recent %}
  <div class="no-data">Результаты появятся после первых сигналов</div>
  {% endif %}
</div>

<!-- ── СИГНАЛЫ ── -->
<div class="section">
  <div class="section-title">Последние сигналы (обновление каждые 30 сек)</div>
  <div style="padding-bottom:24px" id="signals-list">
  {% if signals %}
    {% for s in signals %}
    <div class="sig-card {{ 'long-card' if s.direction=='LONG' else 'short-card' }}"
         data-coin="{{ s.symbol }}">
      <div class="sig-head">
        <span class="sig-sym">
          {{ '🟢' if s.direction=='LONG' else '🔴' }}
          {{ s.direction }} {{ s.symbol }} [{{ s.timeframe }}]
        </span>
        <span class="sig-ts">{{ s.timestamp }} • {{ s.session }}</span>
      </div>
      <div class="sig-grid">
        <div class="sig-item"><div class="lbl">Вход</div>
          <div class="val">{{ s.entry }}</div></div>
        <div class="sig-item"><div class="lbl">Стоп (-{{ s.risk_pct }}%)</div>
          <div class="val" style="color:#f85149">{{ s.stop_loss }}</div></div>
        <div class="sig-item"><div class="lbl">TP1</div>
          <div class="val" style="color:#3fb950">{{ s.tp1 }}</div></div>
        <div class="sig-item"><div class="lbl">TP2</div>
          <div class="val" style="color:#3fb950">{{ s.tp2 }}</div></div>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:.72rem;color:#8b949e">Уверенность {{ s.confidence }}%</span>
        <div class="conf-bar" style="flex:1">
          <div class="conf-fill" style="width:{{ s.confidence }}%"></div>
        </div>
      </div>
      <div class="reasons">{{ s.reasons | join(' • ') }}</div>
    </div>
    {% endfor %}
  {% else %}
    <div class="no-data">⏳ Ожидаем сигналы... Бот сканирует рынок каждые 2 минуты</div>
  {% endif %}
  </div>
</div>

<script>
// Все данные трекера для пересчёта статистики по монете
const trackerData = {{ perf.recent | tojson }};

function winColor(rate) {
  return rate >= 60 ? '#3fb950' : rate >= 40 ? '#d29922' : '#f85149';
}

function filterCoin(coin) {
  // Подсветка активного таба
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.coin === coin));

  // Фильтр строк таблицы результатов
  document.querySelectorAll('.trow').forEach(row => {
    row.classList.toggle('hidden', coin !== 'ALL' && row.dataset.coin !== coin);
  });

  // Фильтр карточек сигналов
  document.querySelectorAll('.sig-card').forEach(card => {
    card.classList.toggle('hidden', coin !== 'ALL' && card.dataset.coin !== coin);
  });

  // Пересчёт статистики для выбранной монеты
  const subset = coin === 'ALL' ? trackerData : trackerData.filter(r => r.symbol === coin);
  const tp2    = subset.filter(r => r.status === 'tp2').length;
  const tp1    = subset.filter(r => r.status === 'tp1').length;
  const sl     = subset.filter(r => r.status === 'sl').length;
  const pend   = subset.filter(r => r.status === 'pending').length;
  const tout   = subset.filter(r => r.status === 'timeout').length;
  const wins   = tp1 + tp2;
  const resolved = wins + sl;
  const wr     = resolved > 0 ? Math.round(wins / resolved * 1000) / 10 : 0;
  const col    = winColor(wr);

  document.getElementById('s-tp2').textContent  = tp2;
  document.getElementById('s-tp1').textContent  = tp1;
  document.getElementById('s-sl').textContent   = sl;
  document.getElementById('s-pend').textContent = pend;
  document.getElementById('s-tout').textContent = tout;
  document.getElementById('wr-pct').textContent = wr + '%';
  document.getElementById('wr-pct').style.color = col;
  document.getElementById('wr-bar').style.width = wr + '%';
  document.getElementById('wr-bar').style.background = col;
  document.getElementById('wr-resolved').textContent = resolved;

  // Счётчики в активности
  const longs  = subset.filter(r => r.direction === 'LONG').length;
  const shorts = subset.filter(r => r.direction === 'SHORT').length;
  if (coin !== 'ALL') {
    document.getElementById('stat-total').textContent = subset.length;
    document.getElementById('stat-long').textContent  = longs;
    document.getElementById('stat-short').textContent = shorts;
  } else {
    document.getElementById('stat-total').textContent = {{ stats.total }};
    document.getElementById('stat-long').textContent  = {{ stats.long }};
    document.getElementById('stat-short').textContent = {{ stats.short }};
  }
}
</script>
</body>
</html>
"""


def add_signal(signal: dict) -> None:
    _signals.appendleft(signal)
    _stats["total"] += 1
    if signal["direction"] == "LONG":
        _stats["long"] += 1
    else:
        _stats["short"] += 1


@app.route("/")
def index():
    from analytics.tracker import get_stats
    perf = get_stats()

    # Собираем все монеты из сигналов и трекера
    coins_set = set()
    for s in _signals:
        coins_set.add(s["symbol"])
    for r in perf["recent"]:
        coins_set.add(r["symbol"])
    all_coins = sorted(coins_set)

    # Кол-во записей в трекере по каждой монете
    coin_counts = {c: sum(1 for r in perf["recent"] if r["symbol"] == c) for c in all_coins}

    return render_template_string(
        DASHBOARD_HTML,
        signals=list(_signals),
        stats=_stats,
        perf=perf,
        all_coins=all_coins,
        coin_counts=coin_counts,
    )


@app.route("/api/signals")
def api_signals():
    return jsonify(list(_signals))


@app.route("/api/stats")
def api_stats():
    from analytics.tracker import get_stats
    return jsonify({"activity": _stats, "performance": get_stats()})


def run_dashboard():
    import logging as _log
    _log.getLogger("werkzeug").setLevel(_log.ERROR)
    logger.info(f"Dashboard starting on http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False, use_reloader=False)
