# 94-879 Track B Starter Kit

A trimmed-down, portable pipeline (Kafka -> features -> model -> MLflow ->
Evidently) for running and diagnosing a real streaming ML system locally.

No live Coinbase connection is required. `data/sample/sample_ticks.jsonl`
is a real 782-message recorded BTC-USD ticker sample; `scripts/replay.py`
publishes it into Kafka to stand in for the live feed.

## Prerequisites

- **Python 3.11 or 3.12.** Newer Pythons (3.13/3.14) don't have prebuilt
  wheels for the pinned data-science packages this kit depends on, which
  triggers a source build that fails. Check with `python3 --version`
  (macOS/Linux) or `python --version` (Windows); if you have a newer
  default, install 3.12 and point the venv creation command at it
  explicitly (e.g. `python3.12 -m venv venv`).
- Docker Desktop (Mac/Windows) or Docker Engine (Linux), installed and
  **running** before you run any command below. On Windows, start Docker
  Desktop first and wait for it to fully launch.

### Creating and activating the virtual environment

macOS / Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

Windows (PowerShell):
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

Windows (Command Prompt):
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

The rest of this README uses macOS/Linux-style commands (bash) but every
command is written on a single line, so it should paste directly into
PowerShell or Command Prompt too. The one exception is JSON quoting in the
`curl -d` command in the Smoke test section below. See the note there if
you're using Command Prompt specifically.

## What's here (and what isn't)

| Kept | Cut |
|---|---|
| Kafka producer/consumer flow (replay -> featurizer) | Live Coinbase WebSocket ingestion |
| `features/featurizer.py` (windowed features) | EDA notebooks |
| One baseline + one small model, logged to MLflow | Full train/val/test model comparison suite |
| A minimal Flask scoring service | PDF report generation |
| One Evidently drift/quality report | Model card / GenAI appendix docs |
| Docker Compose (Kafka, MLflow, scorer) with healthchecks | n/a |

## Quickstart

```bash
cp .env.example .env
pip install -r requirements.txt

# 1. Start the stack
docker compose -f docker/compose.yaml up -d --build

# 2. Replay sample market data into Kafka
python scripts/replay.py --rate 20

# 3. Compute features (run for a bit, then Ctrl+C, or use --max_messages)
python features/featurizer.py --max_messages 400

# 4. Train the baseline + logistic regression model (logs to MLflow)
python models/train_baseline.py

# 5. Rebuild the scorer now that a model artifact exists, and restart it
docker compose -f docker/compose.yaml up -d --build scorer

# 6. Generate a drift/quality report
python monitoring/drift_report.py
```

## Smoke test

Run this sequence after `docker compose up` to confirm the stack is
actually working: five checks, one command block, no custom test script.
Each command's expected output is noted as a comment.

```bash
# 1. Containers running
docker compose -f docker/compose.yaml ps
# Expect: broker, mlflow, scorer all "running (healthy)"

# 2. Kafka reachable
docker compose -f docker/compose.yaml exec broker /opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092
# Expect: broker version info printed, no connection error

# 3. Sample event flow works (replay -> Kafka -> features)
python scripts/replay.py --rate 50
python features/featurizer.py --max_messages 50
# Expect: replay prints "sent 782 messages total to topic 'ticks.raw'";
# featurizer prints "produced 50 feature rows" and exits

# 4. MLflow reachable
curl -sf http://localhost:5001 > /dev/null && echo "MLflow OK"
# Expect: "MLflow OK"

# 5. Scoring service responds (run models/train_baseline.py first if you
# haven't yet -- the scorer needs a model artifact to give a real score)
curl -sf http://localhost:8000/health
curl -s -X POST http://localhost:8000/score -H "Content-Type: application/json" -d "{\"midprice_returns\":0.001,\"spread_normalized\":0.0002,\"order_book_imbalance\":0.1,\"trade_intensity\":12}"
# Expect: {"model_loaded": true, "status": "ok"} then a JSON score
```

> **Windows PowerShell:** `> /dev/null` and `&&` don't work the same way
> on Windows. Use these instead for steps 4 and 5:
> ```powershell
> # 4. MLflow reachable
> curl.exe -sf http://localhost:5001 > $null; if ($LASTEXITCODE -eq 0) { Write-Host "MLflow OK" } else { Write-Host "MLflow NOT OK" }
>
> # 5. Scoring service responds
> curl.exe -sf http://localhost:8000/health
> Invoke-RestMethod -Method Post -Uri http://localhost:8000/score -ContentType "application/json" -Body '{"midprice_returns":0.001,"spread_normalized":0.0002,"order_book_imbalance":0.1,"trade_intensity":12}'
> ```
> If `/health` shows `model_loaded: false`, restart the scorer:
> `docker compose -f docker/compose.yaml restart scorer` (make sure
> `models/train_baseline.py` has been run first, so the artifact exists).

> **Windows Command Prompt note:** the `-d` payload above uses
> double-quotes with escaped inner quotes so it works in `cmd.exe`, where
> single quotes aren't treated as a string delimiter. If you're in
> PowerShell or a Mac/Linux terminal, both single- and double-quoted
> versions work fine.

> **Note:** the first time you run step 2 or 3 against a brand-new topic,
> you may see one `UNKNOWN_TOPIC_OR_PART` message before things settle --
> that's Kafka creating the topic on first write, not a real failure.

`scripts/kafka_consume_check.py` is also available standalone if you want a
scripted pass/fail check on a topic, but it's optional -- the sequence
above is the one to run first.

## Services

| Service | URL | Notes |
|---|---|---|
| Kafka | `localhost:9092` | KRaft mode, no Zookeeper |
| MLflow | http://localhost:5001 | SQLite backend |
| Scorer | http://localhost:8000 | `GET /health`, `POST /score` |

## Repository layout

```
docker/          compose.yaml, Dockerfile.scorer
scripts/         replay.py, kafka_consume_check.py
features/        featurizer.py (shared by live + replay)
models/          train_baseline.py, artifacts/ (created at train time)
scoring/         score_service.py
monitoring/      drift_report.py
data/sample/     sample_ticks.jsonl (recorded, replayable)
```

## Acknowledgments

This starter kit is based on a foundation submission by Matt Yarkunas
(94-879, prior semester), used with his permission.
