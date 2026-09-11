"""
scripts/kafka_consume_check.py

Minimal readiness check: subscribe to a topic and confirm at least N
messages arrive within a timeout. Exits 0 on success, 1 on failure, so it
can be used both interactively and inside the smoke test script.
"""
import argparse
import os
import sys
import time


def check(broker, topic, min_messages, timeout_seconds):
    from quixstreams import Application

    app = Application(
        broker_address=broker,
        consumer_group=f"consume_check_{int(time.time())}",  # unique group -> always reads fresh
        auto_offset_reset="earliest",
    )
    count = 0
    deadline = time.time() + timeout_seconds
    with app.get_consumer() as consumer:
        consumer.subscribe([topic])
        print(f"[check] subscribed to '{topic}', waiting for {min_messages} message(s)...")
        while time.time() < deadline and count < min_messages:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error() is not None:
                print(f"[check] consumer error: {msg.error()}")
                continue
            count += 1

    if count >= min_messages:
        print(f"[check] OK: saw {count} message(s) on '{topic}'")
        return True
    print(f"[check] FAIL: only saw {count}/{min_messages} message(s) on '{topic}' "
          f"within {timeout_seconds}s")
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check that a Kafka topic is receiving messages")
    parser.add_argument("--broker", default=os.environ.get("KAFKA_BROKER", "localhost:9092"))
    parser.add_argument("--topic", default="ticks.raw")
    parser.add_argument("--min", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    ok = check(args.broker, args.topic, args.min, args.timeout)
    sys.exit(0 if ok else 1)
