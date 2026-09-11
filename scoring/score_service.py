"""
scoring/score_service.py

A minimal HTTP scoring service. Loads the pickled model produced by
models/train_baseline.py and exposes two endpoints:

  GET  /health          -> {"status": "ok", "model_loaded": bool}
  POST /score           -> {"score": float, "spike": bool}
                            body: {"midprice_returns": .., "spread_normalized": ..,
                                    "order_book_imbalance": .., "trade_intensity": ..}

Deliberately framework-light (Flask) and single-file so the whole thing
can be read in one sitting.
"""
import os
import pickle

import pandas as pd
from flask import Flask, jsonify, request

MODEL_PATH = os.environ.get("MODEL_PATH", "models/artifacts/model.pkl")
FEATURE_COLUMNS = ["midprice_returns", "spread_normalized", "order_book_imbalance", "trade_intensity"]

app = Flask(__name__)
_state = {"model": None, "scaler": None}


def load_model():
    with open(MODEL_PATH, "rb") as f:
        bundle = pickle.load(f)
    _state["model"] = bundle["model"]
    _state["scaler"] = bundle["scaler"]
    print(f"[score_service] loaded model from {MODEL_PATH}")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model_loaded": _state["model"] is not None})


@app.route("/score", methods=["POST"])
def score():
    if _state["model"] is None:
        return jsonify({"error": "model not loaded"}), 503

    payload = request.get_json(force=True)
    missing = [c for c in FEATURE_COLUMNS if c not in payload]
    if missing:
        return jsonify({"error": f"missing fields: {missing}"}), 400

    x = pd.DataFrame([{c: payload[c] for c in FEATURE_COLUMNS}])
    x_scaled = _state["scaler"].transform(x)
    prob = float(_state["model"].predict_proba(x_scaled)[0, 1])
    return jsonify({"score": prob, "spike": prob >= 0.5})


if __name__ == "__main__":
    try:
        load_model()
    except FileNotFoundError:
        print(f"[score_service] WARNING: no model found at {MODEL_PATH}. "
              f"Run models/train_baseline.py first. Starting anyway (health check will report model_loaded=false).")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
