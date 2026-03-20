# Vercel Deployment Edition

This folder is a standalone deployment root for Vercel.

## What is included

- `app_core.py`: relic normalization, Wiki drop parsing, market price lookup, EV calculation
- `app.py`: FastAPI app (`/`, `/api/health`, `/api/ev`)
- `api/index.py`: Vercel Python entrypoint
- `vercel.json`: Vercel build and route config
- `requirements.txt`: minimal runtime deps for web deployment
- `smoke_test.py`: tiny runtime check script

## API

`GET /api/ev`

Query params:

- `relic`: e.g. `Meso A6` or `中纪A6`
- `refinement`: `intact|exceptional|flawless|radiant`
- `status`: `ingame|online|any`

Example response:

```json
{
  "ok": true,
  "relic": "Meso A6",
  "vault_status": "active",
  "ev": 12.34,
  "drops": []
}
```

Notes:

- `Forma Blueprint` is fixed to `1p` and skips market lookup.
- This serverless edition does not rely on writing local JSON cache files.

## Local run

```powershell
cd "C:\Users\pc\Desktop\随手文件\warframe小工具\核桃查询\vercel版本"
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open: `http://127.0.0.1:8000`

## Local smoke test

```powershell
cd "C:\Users\pc\Desktop\随手文件\warframe小工具\核桃查询\vercel版本"
python smoke_test.py
```

## Deploy to Vercel

1. Push this folder to your GitHub repo (already done for repo).
2. In Vercel, import the repo.
3. Set **Root Directory** to `vercel版本`.
4. Deploy.

