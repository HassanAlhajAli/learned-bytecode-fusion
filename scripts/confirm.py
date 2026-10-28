"""Remeasure frozen final choices in interleaved, independent benchmark runs."""

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

from experiment import DATA, EXECUTABLE, WORKLOADS, invoke_vm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("final", "stress"), default="final")
    parser.add_argument("--count", type=int, default=2_000_000)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if min(args.count, args.repetitions, args.rounds) < 1:
        raise ValueError("benchmark parameters must be positive")
    results = json.loads((DATA / f"{args.split}_results.json").read_text(encoding="utf-8"))
    original = json.loads((DATA / f"{args.split}_measurements.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(EXECUTABLE.read_bytes()).hexdigest()
    if digest != original["binary_sha256"]:
        raise RuntimeError("VM binary changed since the final comparison")
    rng = random.Random(1938)
    raw = {}
    for name, expression in WORKLOADS[args.split].items():
        selected = {0}
        for method in results["methods"].values():
            selected.add(method["cases"][name]["mask"])
        samples = {str(mask): [] for mask in selected}
        checksums = set()
        for _ in range(args.rounds):
            order = sorted(selected)
            rng.shuffle(order)
            for mask in order:
                sample = invoke_vm(expression, mask, args.count, args.repetitions)
                samples[str(mask)].append(sample["median_ns_per_item"])
                checksums.add(sample["checksum"])
        if len(checksums) != 1:
            raise RuntimeError(f"checksum mismatch in {name}")
        raw[name] = {"expression": expression, "samples_ns_per_item": samples,
                     "checksum": checksums.pop()}
        print(f"Confirmed {name}: {len(selected)} choices, {args.rounds} rounds")
    summary = {}
    for method, result in results["methods"].items():
        speedups = {}
        for name in raw:
            mask = result["cases"][name]["mask"]
            baseline = statistics.median(raw[name]["samples_ns_per_item"]["0"])
            chosen = statistics.median(raw[name]["samples_ns_per_item"][str(mask)])
            speedups[name] = baseline / chosen
        summary[method] = {
            "geometric_mean_speedup": math.exp(statistics.mean(
                math.log(value) for value in speedups.values())),
            "case_speedups": speedups,
        }
    output = {"split": args.split, "count": args.count, "repetitions": args.repetitions,
              "rounds": args.rounds, "binary_sha256": digest,
              "selected_from": f"data/{args.split}_results.json", "raw": raw, "methods": summary}
    (DATA / f"{args.split}_confirmation.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8")
    for method, result in summary.items():
        print(f"{method}: {result['geometric_mean_speedup']:.3f}x confirmed speedup")


if __name__ == "__main__":
    main()
