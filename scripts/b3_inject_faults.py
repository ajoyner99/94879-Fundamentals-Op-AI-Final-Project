"""
scripts/b3_inject_faults.py

B3 scenario S3: simulate an upstream feed that loses messages. Keeps every
other ticker message from the reference recording (non-ticker messages are
left alone) and writes a new .jsonl to replay through Kafka like any other
sample file. Timestamps are untouched, so the featurizer's 60 s trade_intensity window
counts only the messages that remain. This is a constructed fault, used to
check whether the monitor reacts to a known change; it is not taken from a
real incident.

Prints the number of ticker rows the featurizer should produce, to pass as
--max_messages.
"""
import argparse
import json


def is_ticker(line):
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return False
    return any(e.get("type") in ("update", "snapshot") and "tickers" in e for e in data.get("events", []))


def main(src, dst, keep_every):
    with open(src) as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]

    out, tickers_seen, tickers_kept = [], 0, 0
    for line in lines:
        if is_ticker(line):
            if tickers_seen % keep_every == 0:
                out.append(line)
                tickers_kept += 1
            tickers_seen += 1
        else:
            out.append(line)

    with open(dst, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"[inject] {src}: {tickers_seen} ticker messages -> kept {tickers_kept} (1 in {keep_every})")
    print(f"[inject] wrote {len(out)} lines to {dst}")
    print(f"[inject] use --max_messages {tickers_kept} for the featurizer")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default="data/sample/sample_ticks.jsonl")
    parser.add_argument("--dst", default="data/sample/sample_ticks_msgloss.jsonl")
    parser.add_argument("--keep_every", type=int, default=2, help="Keep 1 of every N ticker messages.")
    args = parser.parse_args()
    main(args.src, args.dst, args.keep_every)
