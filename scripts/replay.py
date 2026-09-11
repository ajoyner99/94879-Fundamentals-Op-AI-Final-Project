"""
scripts/replay.py

Replays a saved slice of raw Coinbase ticker data into the ticks.raw Kafka
topic, standing in for a live WebSocket feed. Deterministic and has no
network dependency; --rate controls how fast messages are published.

Usage:
    python scripts/replay.py --file data/sample/sample_ticks.jsonl --rate 20
"""
import argparse
import json
import os
import time


def load_lines(path):
    with open(path, "r") as f:
        return [line.strip() for line in f if line.strip()]


def replay(path, broker, topic, rate, loop):
    from quixstreams import Application

    app = Application(broker_address=broker)
    producer = app.get_producer()
    lines = load_lines(path)
    print(f"[replay] loaded {len(lines)} recorded messages from {path}")
    delay = 1.0 / rate if rate > 0 else 0

    sent = 0
    while True:
        for line in lines:
            producer.produce(topic=topic, key="BTC-USD", value=line)
            sent += 1
            if sent % 100 == 0:
                print(f"[replay] sent {sent} messages (rate={rate}/s)")
            if delay:
                time.sleep(delay)
        if not loop:
            break
    producer.flush()
    print(f"[replay] done. sent {sent} messages total to topic '{topic}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay recorded ticks into Kafka")
    parser.add_argument("--file", default="data/sample/sample_ticks.jsonl")
    parser.add_argument("--broker", default=os.environ.get("KAFKA_BROKER", "localhost:9092"))
    parser.add_argument("--topic", default="ticks.raw")
    parser.add_argument("--rate", type=float, default=20.0,
                         help="Messages per second to publish.")
    parser.add_argument("--loop", action="store_true",
                         help="Keep replaying the file on a loop instead of stopping at EOF")
    args = parser.parse_args()
    replay(args.file, args.broker, args.topic, args.rate, args.loop)
