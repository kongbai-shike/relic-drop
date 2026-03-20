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
    body { font-family: Arial, sans-serif; max-width: 980px; margin: 20px auto; padding: 0 12px; }
    input, select, button { padding: 6px 8px; margin-right: 8px; }
    table { border-collapse: collapse; width: 100%; margin-top: 12px; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background: #f5f5f5; }
    .muted { color: #666; }
  </style>
</head>
<body>
  <h2>Warframe Relic EV</h2>
  <p class="muted">Serverless Vercel edition.</p>
  <div>
    <input id="relic" placeholder="Meso A6 / 中纪A6" value="Meso A6" />
    <select id="refinement">
      <option value="intact">intact</option>
      <option value="exceptional">exceptional</option>
      <option value="flawless">flawless</option>
      <option value="radiant" selected>radiant</option>
    </select>
    <select id="status">
      <option value="ingame" selected>ingame</option>
      <option value="online">online</option>
      <option value="any">any</option>
    </select>
    <button onclick="queryEv()">Query</button>
  </div>

  <p id="summary"></p>
  <table id="table" style="display:none;">
    <thead>
      <tr>
        <th>Rarity</th>
        <th>Prob%</th>
        <th>Price(p)</th>
        <th>EV</th>
        <th>Item</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>

<script>
async function queryEv() {
  const relic = document.getElementById('relic').value.trim();
  const refinement = document.getElementById('refinement').value;
  const status = document.getElementById('status').value;
  const summary = document.getElementById('summary');
  const table = document.getElementById('table');
  const tbody = table.querySelector('tbody');

  summary.textContent = 'Loading...';
  table.style.display = 'none';
  tbody.innerHTML = '';

  const url = `/api/ev?relic=${encodeURIComponent(relic)}&refinement=${encodeURIComponent(refinement)}&status=${encodeURIComponent(status)}`;
  const resp = await fetch(url);
  const data = await resp.json();

  if (!data.ok) {
    summary.textContent = `Error: ${data.error}`;
    return;
  }

  summary.textContent = `${data.relic} | vault: ${data.vault_status} | EV: ${data.ev}p`;
  for (const row of data.drops) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.rarity}</td>
      <td>${row.prob}</td>
      <td>${row.price === null ? 'N/A' : row.price}</td>
      <td>${row.value === null ? 'N/A' : row.value.toFixed(4)}</td>
      <td>${row.item}</td>
    `;
    tbody.appendChild(tr);
  }
  table.style.display = '';
}
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

