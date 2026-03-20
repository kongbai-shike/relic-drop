from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app_core import calculate_relic_ev


app = FastAPI(title="Warframe Relic EV Web", version="0.1.0")


INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Relic EV</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f1117;
      --panel: #171b26;
      --panel-2: #1f2432;
      --text: #e6eaf2;
      --muted: #9ba3b4;
      --line: #2a3142;
      --accent: #62a4ff;
      --accent-2: #4d89db;
    }
    * { box-sizing: border-box; }
    body {
      font-family: Arial, sans-serif;
      max-width: 1060px;
      margin: 0 auto;
      padding: 20px 12px 32px;
      background: var(--bg);
      color: var(--text);
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      margin-top: 12px;
    }
    .top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    .title { margin: 0; font-size: 24px; }
    .muted { color: var(--muted); margin-top: 6px; }
    .form {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .form input, .form select {
      background: var(--panel-2);
      color: var(--text);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      min-height: 38px;
    }
    .form input { min-width: 220px; }
    .btn {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-2);
      color: var(--text);
      padding: 8px 12px;
      cursor: pointer;
    }
    .btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    .btn.primary:hover { background: var(--accent-2); border-color: var(--accent-2); }
    #summary { margin: 0; white-space: pre-wrap; }
    table {
      border-collapse: collapse;
      width: 100%;
      margin-top: 8px;
      overflow: hidden;
      border-radius: 10px;
      border: 1px solid var(--line);
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
      text-align: left;
    }
    th { background: var(--panel-2); }
    tr:nth-child(even) td { background: #141a26; }
    .settings {
      display: none;
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
    }
    .settings label { color: var(--muted); margin-right: 8px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="top">
      <div>
        <h2 class="title" data-i18n="title">Warframe Relic EV</h2>
        <p class="muted" data-i18n="subtitle">Serverless Vercel edition.</p>
      </div>
      <button class="btn" id="settingsBtn" data-i18n="settings" onclick="toggleSettings()">Settings</button>
    </div>

    <div id="settingsPanel" class="settings">
      <label for="langSelect" data-i18n="language">Language</label>
      <select id="langSelect" onchange="onLanguageChange()">
        <option value="zh_CN">简体中文</option>
        <option value="en_US">English</option>
      </select>
    </div>
  </div>

  <div class="card">
    <div class="form">
      <input id="relic" placeholder="Meso A6 / 中纪A6" value="Meso A6" />
      <select id="refinement" aria-label="refinement">
        <option value="intact" data-i18n="ref_intact">intact</option>
        <option value="exceptional" data-i18n="ref_exceptional">exceptional</option>
        <option value="flawless" data-i18n="ref_flawless">flawless</option>
        <option value="radiant" data-i18n="ref_radiant" selected>radiant</option>
    </select>
      <select id="status" aria-label="status">
        <option value="ingame" data-i18n="status_ingame" selected>ingame</option>
        <option value="online" data-i18n="status_online">online</option>
        <option value="any" data-i18n="status_any">any</option>
      </select>
      <button class="btn primary" id="queryBtn" data-i18n="query" onclick="queryEv()">Query</button>
  </div>
  </div>

  <div class="card">
    <p id="summary"></p>
    <table id="table" style="display:none;">
      <thead>
        <tr>
          <th data-i18n="col_rarity">Rarity</th>
          <th data-i18n="col_prob">Prob%</th>
          <th data-i18n="col_price">Price(p)</th>
          <th data-i18n="col_ev">EV</th>
          <th data-i18n="col_item">Item</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>

<script>
const I18N = {
  zh_CN: {
    title: 'Warframe 遗物 EV 查询',
    subtitle: 'Vercel 无服务器版本',
    settings: '设置',
    language: '界面语言',
    query: '查询',
    loading: '查询中...',
    error: '错误',
    summary: '{relic} | 状态: {vault} | EV: {ev}p',
    vault_label: { vaulted: '入库', active: '出库', unknown: '未知' },
    rarity_label: { common: '普通', uncommon: '罕见', rare: '稀有' },
    col_rarity: '稀有度',
    col_prob: '概率%',
    col_price: '价格(p)',
    col_ev: 'EV',
    col_item: '掉落物',
    na: '无',
    ref_intact: '完好',
    ref_exceptional: '优良',
    ref_flawless: '无暇',
    ref_radiant: '辉耀',
    status_ingame: '游戏内',
    status_online: '在线',
    status_any: '任意',
  },
  en_US: {
    title: 'Warframe Relic EV',
    subtitle: 'Serverless Vercel edition',
    settings: 'Settings',
    language: 'Language',
    query: 'Query',
    loading: 'Loading...',
    error: 'Error',
    summary: '{relic} | vault: {vault} | EV: {ev}p',
    vault_label: { vaulted: 'Vaulted', active: 'Active', unknown: 'Unknown' },
    rarity_label: { common: 'common', uncommon: 'uncommon', rare: 'rare' },
    col_rarity: 'Rarity',
    col_prob: 'Prob%',
    col_price: 'Price(p)',
    col_ev: 'EV',
    col_item: 'Item',
    na: 'N/A',
    ref_intact: 'intact',
    ref_exceptional: 'exceptional',
    ref_flawless: 'flawless',
    ref_radiant: 'radiant',
    status_ingame: 'ingame',
    status_online: 'online',
    status_any: 'any',
  }
};

let currentLang = localStorage.getItem('ui_lang') || 'zh_CN';

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || key;
}

function vaultLabel(code) {
  const m = I18N[currentLang].vault_label || {};
  return m[code] || m.unknown || code;
}

function rarityLabel(code) {
  const m = I18N[currentLang].rarity_label || {};
  return m[code] || code;
}

function applyLanguage() {
  document.documentElement.lang = currentLang === 'zh_CN' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    const key = el.getAttribute('data-i18n');
    if (key && I18N[currentLang][key]) {
      el.textContent = I18N[currentLang][key];
    }
  });

  const relicInput = document.getElementById('relic');
  relicInput.placeholder = currentLang === 'zh_CN' ? '例如: 中纪A6 / Meso A6' : 'e.g. Meso A6 / 中纪A6';
  document.getElementById('langSelect').value = currentLang;

  document.querySelectorAll('td[data-rarity]').forEach((td) => {
    const raw = td.getAttribute('data-rarity') || '';
    td.textContent = rarityLabel(raw);
  });
}

function onLanguageChange() {
  currentLang = document.getElementById('langSelect').value;
  localStorage.setItem('ui_lang', currentLang);
  applyLanguage();
}

function toggleSettings() {
  const panel = document.getElementById('settingsPanel');
  panel.style.display = panel.style.display === 'block' ? 'none' : 'block';
}

async function queryEv() {
  const relic = document.getElementById('relic').value.trim();
  const refinement = document.getElementById('refinement').value;
  const status = document.getElementById('status').value;
  const summary = document.getElementById('summary');
  const table = document.getElementById('table');
  const tbody = table.querySelector('tbody');
  const queryBtn = document.getElementById('queryBtn');

  summary.textContent = t('loading');
  table.style.display = 'none';
  tbody.innerHTML = '';
  queryBtn.disabled = true;

  try {
    const url = `/api/ev?relic=${encodeURIComponent(relic)}&refinement=${encodeURIComponent(refinement)}&status=${encodeURIComponent(status)}`;
    const resp = await fetch(url);
    const data = await resp.json();

    if (!data.ok) {
      summary.textContent = `${t('error')}: ${data.error}`;
      return;
    }

    summary.textContent = t('summary')
      .replace('{relic}', data.relic)
      .replace('{vault}', vaultLabel(data.vault_status))
      .replace('{ev}', data.ev);

    for (const row of data.drops) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td data-rarity="${row.rarity}">${rarityLabel(row.rarity)}</td>
        <td>${row.prob}</td>
        <td>${row.price === null ? t('na') : row.price}</td>
        <td>${row.value === null ? t('na') : row.value.toFixed(4)}</td>
        <td>${row.item}</td>
      `;
      tbody.appendChild(tr);
    }
    table.style.display = '';
  } catch (err) {
    summary.textContent = `${t('error')}: ${err}`;
  } finally {
    queryBtn.disabled = false;
  }
}

applyLanguage();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/ev")
def get_ev(
    relic: str = Query(..., description="Relic name, e.g. Meso A6"),
    refinement: str = Query("radiant", pattern="^(intact|exceptional|flawless|radiant)$"),
    status: str = Query("ingame", pattern="^(ingame|online|any)$"),
) -> JSONResponse:
    try:
        result = calculate_relic_ev(relic_name=relic, refinement=refinement, status_filter=status)
        return JSONResponse({"ok": True, **result})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})

