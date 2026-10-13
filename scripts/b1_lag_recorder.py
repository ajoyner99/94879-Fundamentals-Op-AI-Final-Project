"""
scripts/b1_lag_recorder.py

Records Kafka consumer lag over time for Challenge B1.

Every --interval seconds, this runs the same `kafka-consumer-groups.sh --describe`
command you ran by hand (inside the `broker` container), pulls out
CURRENT-OFFSET, LOG-END-OFFSET and LAG for featurizer_group / ticks.raw,
and appends one timestamped row to a CSV file. Stop it with Ctrl+C.

Usage (from the project folder, in its own terminal):
    python scripts/b1_lag_recorder.py --label rate500_trial2
"""
import argparse
import csv
import os
import subprocess
import time
from datetime import datetime


def parse_describe(text, group, topic):
    """Find our group/topic row in the --describe output.
    Returns (current_offset, log_end_offset, lag, consumer_active) or None."""
    for line in text.splitlines():
        parts = line.split()
        # Row format: GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG CONSUMER-ID HOST CLIENT-ID
        if len(parts) >= 6 and parts[0] == group and parts[1] == topic:
            def to_int(s):
                return int(s) if s.isdigit() else None  # Kafka prints "-" when unknown
            active = len(parts) >= 7 and parts[6] != "-"
            return to_int(parts[3]), to_int(parts[4]), to_int(parts[5]), active
    return None


def read_offsets(container, broker, group, topic):
    """Run the describe command inside the Kafka container and parse it."""
    cmd = ["docker", "exec", container,
           "/opt/kafka/bin/kafka-consumer-groups.sh",
           "--bootstrap-server", broker, "--describe", "--group", group]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        print("[recorder] describe command timed out")
        return None
    if result.returncode != 0:
        print(f"[recorder] describe command failed: {result.stderr.strip()}")
        return None
    return parse_describe(result.stdout, group, topic)


def main():
    p = argparse.ArgumentParser(description="Record Kafka consumer lag over time (B1)")
    p.add_argument("--label", default="run", help="Short name for this run, used in the file name")
    p.add_argument("--interval", type=float, default=5.0, help="Seconds between samples")
    p.add_argument("--out", default=None, help="CSV path (default: data/b1_runs/lag_<label>_<time>.csv)")
    p.add_argument("--container", default="broker")
    p.add_argument("--broker", default="localhost:9092")
    p.add_argument("--group", default="featurizer_group")
    p.add_argument("--topic", default="ticks.raw")
    args = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.out or os.path.join("data", "b1_runs", f"lag_{args.label}_{stamp}.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    columns = ["wall_time", "elapsed_s", "current_offset", "log_end_offset", "lag",
               "consumer_active", "arrival_rate_per_s", "processing_rate_per_s"]
    print(f"[recorder] sampling every {args.interval}s -> {out_path}  (Ctrl+C to stop)")

    start = time.monotonic()
    prev = None  # (elapsed, current_offset, log_end_offset) from the previous good sample
    sample = 0
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        try:
            while True:
                reading = read_offsets(args.container, args.broker, args.group, args.topic)
                elapsed = round(time.monotonic() - start, 1)
                wall = datetime.now().isoformat(timespec="seconds")

                if reading is None:
                    print(f"[recorder] {wall} no data for {args.group}/{args.topic} yet")
                else:
                    current, log_end, lag, active = reading
                    arrival = processing = ""
                    # Rates = how much each offset moved since the last sample, per second
                    if prev and None not in (current, log_end, prev[1], prev[2]):
                        dt = elapsed - prev[0]
                        if dt > 0:
                            arrival = round((log_end - prev[2]) / dt, 1)
                            processing = round((current - prev[1]) / dt, 1)
                    writer.writerow([wall, elapsed, current, log_end, lag, active, arrival, processing])
                    f.flush()  # save each row immediately, so nothing is lost on Ctrl+C
                    print(f"[recorder] t={elapsed:>6}s  current={current}  log_end={log_end}  "
                          f"lag={lag}  arrival/s={arrival}  processed/s={processing}")
                    prev = (elapsed, current, log_end)

                # Wait until the next scheduled sample time (keeps samples evenly spaced)
                sample += 1
                time.sleep(max(0.0, start + sample * args.interval - time.monotonic()))
        except KeyboardInterrupt:
            print(f"\n[recorder] stopped. {sample} samples saved to {out_path}")


if __name__ == "__main__":
    main()
