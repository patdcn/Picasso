# Picasso — DSV Picasso Engineering Portal

Multi-tool engineering portal for DSV Picasso operations (DCN Diving), built with Dash.
Deployed via Dokploy on a Contabo VPS.

## Current state

Minimal foundation — one home page that serves as a deploy smoke test. Confirms the
chain works (GitHub push → Dokploy build → container → reachable) before real tools
are ported in.

## Structure

```
picasso/
├── Dockerfile            # production image (gunicorn)
├── docker-compose.yml    # web service (worker/redis/postgres added later)
├── requirements.txt
└── app/
    ├── main.py           # Dash app factory, exposes `server`
    └── pages/
        └── home.py       # smoke-test landing page
```

## Roadmap

1. ✅ Foundation + smoke test
2. ⬜ Port 140T main hoist envelope tool (engine + page)
3. ⬜ Add Postgres + result-object pattern + saved cases
4. ⬜ Add Celery + Redis for slow runs (RAO)
5. ⬜ Report generation (docx/pdf)
6. ⬜ Twin-bell, seafastening, RAO tools

## Run locally

```bash
pip install -r requirements.txt
python -m app.main
# http://localhost:8050
```
