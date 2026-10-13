# B2 reliability

This file is only the B2 reliability work. The starter quickstart stays in README.md.

## What runs where

Replay, the featurizer, and training are host scripts (`scripts/replay.py`, `features/featurizer.py`, `models/train_baseline.py`). Docker runs the broker, MLflow, and the scorer.

The scorer loads `models/artifacts/model.pkl`. It does not read Kafka or MLflow on a score request. MLflow does not talk to the broker.

| Piece | Where |
|---|---|
| Broker | `localhost:9092` |
| MLflow | http://localhost:5001 |
| Scorer | http://localhost:8000 (`GET /health`, `POST /score`) |

## The failure

The original B2 file set `MODEL_PATH` to `/app/models/artifact/model.pkl` (singular `artifact`). The volume is `models/artifacts`. `GET /health` still returned 200 with `model_loaded` false. `POST /score` returned 503. The old healthcheck only opened the URL, so Docker said healthy:

```text
python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
```

## The changes

`docker/docker-compose.b2-challenge.yaml` holds the path, the health check, and `restart: unless-stopped`. `docker/compose.yaml` was not edited. `GET /health` returns the same JSON, with HTTP 503 when the model is missing and HTTP 200 when it is loaded. The scorer image copies `scoring/score_service.py`.

- `MODEL_PATH` is `/app/models/artifacts/model.pkl` again.
- The healthcheck exits 0 only when `status` is `ok` and `model_loaded` is true:

```text
python -c "import json,urllib.request; body=json.load(urllib.request.urlopen('http://localhost:8000/health')); ok=body.get('status')=='ok' and body.get('model_loaded') is True; raise SystemExit(0 if ok else 1)"
```

- The scorer has `restart: unless-stopped`.

## Start the fixed stack

From the project directory:

```bash
docker compose -f docker/docker-compose.b2-challenge.yaml up -d
```

The real score needs `models/artifacts/model.pkl` from the starter quickstart (`python models/train_baseline.py` in README.md).

## Check

```bash
docker compose -f docker/docker-compose.b2-challenge.yaml ps
curl -sf http://localhost:8000/health
curl -s -X POST http://localhost:8000/score -H "Content-Type: application/json" -d "{\"midprice_returns\":0.001,\"spread_normalized\":0.0002,\"order_book_imbalance\":0.1,\"trade_intensity\":12}"
```

Expect `model_loaded` true and `{"score":1.0,"spike":true}` when the real model is loaded. Windows quoting for that `curl` is in the Smoke test section of README.md.

## Results

- `GET /health` is HTTP 503 when the model is missing.
- With the wrong path, before that status change, 51 `POST /score` calls returned HTTP 503 and Docker was unhealthy 51.304 seconds after recreate. `GET /health` was still HTTP 200. After the status change, Docker was unhealthy 51.293 seconds after recreate, and a status-only open of `/health` failed.
- A crash comes back, and an unhealthy-but-running process does not.
- Score latency median was 3.84 ms baseline vs 3.07 ms B2 (n=100, same image and model).
- A plain-text file crash-loops.
- A different scikit-learn model that loads stays healthy and returns a near-zero score with spike false.

## What this README is not

Kubernetes, a second replica, or a pin of `apache/kafka:latest`.
