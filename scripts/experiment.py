"""Measure bytecode fusion choices and train a small policy-gradient agent."""

import argparse
import hashlib
import itertools
import json
import math
import platform
import random
import statistics
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / "build" / ("fusion_vm.exe" if platform.system() == "Windows" else "fusion_vm")
DATA = ROOT / "data"
FUSIONS = [
    ("constant", "add", "constant+add"),
    ("constant", "multiply", "constant+multiply"),
    ("constant", "subtract", "constant+subtract"),
    ("x", "add", "load_x+add"),
    ("y", "add", "load_y+add"),
    ("x", "multiply", "load_x+multiply"),
    ("y", "multiply", "load_y+multiply"),
    ("multiply", "add", "multiply+add"),
    ("add", "multiply", "add+multiply"),
]
WORKLOADS = {
    "train": {
        "affine_x": "x 3 * y +",
        "affine_y": "y 5 * x +",
        "mul_add": "x y * 7 +",
        "add_mul": "x y + 4 *",
        "x_shift": "x 2 + y *",
        "pair_products": "x 2 * y 3 * +",
        "subtract_mix": "x 7 - y 2 * +",
        "product_tail": "y x * 4 + x *",
        "two_offsets": "x 2 + y 3 + *",
        "sum_tail": "x y + 2 * y +",
        "double_x": "x 3 * x + y 5 * +",
        "subtract_y": "y 2 - x 3 * +",
    },
    "test": {
        "heldout_affine": "x 5 * y 3 + +",
        "heldout_offset": "y x + 7 * x 2 + +",
        "heldout_product": "x y * 3 + y 2 * +",
        "heldout_subtract": "y 4 - x y * +",
    },
    "final": {
        "final_nested": "x 2 * y 5 + x + *",
        "final_two_terms": "y 4 * x 3 + +",
        "final_product": "x y * 6 + x 2 * +",
        "final_subtract": "x 8 - y 4 * + x +",
    },
}


def make_stress_workloads():
    """Generate varied, reproducible expressions without looking at timings."""
    rng = random.Random(20261028)
    programs = {}
    while len(programs) < 20:
        terms = []
        for _ in range(rng.randint(2, 4)):
            left = rng.choice(("x", "y"))
            right = rng.choice(("x", "y", str(rng.randint(2, 9))))
            operation = rng.choice(("+", "-", "*"))
            terms.append(f"{left} {right} {operation}")
        expression = terms[0]
        for term in terms[1:]:
            expression += f" {term} {rng.choice(('+', '*'))}"
        kinds = instruction_types(expression)
        active = sum(any((a, b) == (first, second)
                         for a, b in zip(kinds, kinds[1:]))
                     for first, second, _ in FUSIONS)
        if active >= CHOOSE and expression not in programs.values():
            programs[f"stress_{len(programs):02d}"] = expression
    return programs


CHOOSE = 2
MASKS = [sum(1 << action for action in pair)
         for pair in itertools.combinations(range(len(FUSIONS)), CHOOSE)]


def instruction_types(expression):
    result = []
    for token in expression.split():
        result.append({"+": "add", "-": "subtract", "*": "multiply"}.get(
            token, token if token in ("x", "y") else "constant"))
    return result


WORKLOADS["stress"] = make_stress_workloads()


def features(expression, selected):
    kinds = instruction_types(expression)
    pair_counts = [sum((a, b) == (first, second)
                       for a, b in zip(kinds, kinds[1:]))
                   for first, second, _ in FUSIONS]
    return [1.0] + [float(count) for count in pair_counts] + [
        float(selected & (1 << action) != 0) for action in range(len(FUSIONS))
    ] + [len(kinds) / 10.0]


def invoke_vm(expression, mask, count, repetitions):
    command = [str(EXECUTABLE), "--expr", expression, "--mask", str(mask),
               "--count", str(count), "--repetitions", str(repetitions)]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    if result["mask"] != mask or result["median_ns_per_item"] <= 0:
        raise RuntimeError("invalid VM measurement")
    return result


def measure(split, count, repetitions):
    if not EXECUTABLE.is_file():
        raise FileNotFoundError(f"Build the VM first: {EXECUTABLE}")
    rng = random.Random(8102 if split == "train" else 9102)
    measurements = {}
    for name, expression in WORKLOADS[split].items():
        masks = [0] + MASKS.copy()
        rng.shuffle(masks)
        records = {}
        checksums = set()
        for mask in masks:
            sample = invoke_vm(expression, mask, count, repetitions)
            records[str(mask)] = sample
            checksums.add(sample["checksum"])
        if len(checksums) != 1:
            raise RuntimeError(f"Mismatch across fusion choices for {name}")
        measurements[name] = {"expression": expression, "measurements": records}
        print(f"Measured {name}: {len(records)} valid choices")
    DATA.mkdir(exist_ok=True)
    output = {
        "split": split,
        "count": count,
        "repetitions": repetitions,
        "choose": CHOOSE,
        "binary_sha256": hashlib.sha256(EXECUTABLE.read_bytes()).hexdigest(),
        "platform": platform.platform(),
        "workloads": measurements,
    }
    path = DATA / f"{split}_measurements.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output


def read_measurements(split):
    path = DATA / f"{split}_measurements.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["split"] != split or data["choose"] != CHOOSE:
        raise RuntimeError("measurement protocol mismatch")
    if data["binary_sha256"] != hashlib.sha256(EXECUTABLE.read_bytes()).hexdigest():
        raise RuntimeError("VM binary changed since measurement")
    if set(data["workloads"]) != set(WORKLOADS[split]):
        raise RuntimeError("workload split changed since measurement")
    return data


def runtime(workload, mask):
    return workload["measurements"][str(mask)]["median_ns_per_item"]


def reward(workload, mask):
    return math.log(runtime(workload, 0) / runtime(workload, mask))


def probabilities(weights, state, selected):
    legal = [action for action in range(len(FUSIONS))
             if not selected & (1 << action) and state[action + 1] > 0]
    if not legal:
        raise RuntimeError("expression has fewer active fusion rules than the action budget")
    logits = [sum(w * x for w, x in zip(weights[action], state)) for action in legal]
    peak = max(logits)
    unnormalized = [math.exp(logit - peak) for logit in logits]
    total = sum(unnormalized)
    return dict(zip(legal, [value / total for value in unnormalized]))


def select(expression, weights, rng=None):
    selected = 0
    history = []
    for _ in range(CHOOSE):
        state = features(expression, selected)
        distribution = probabilities(weights, state, selected)
        if rng is None:
            action = max(distribution, key=distribution.get)
        else:
            draw = rng.random()
            action = list(distribution)[-1]
            for candidate, chance in distribution.items():
                draw -= chance
                if draw <= 0:
                    action = candidate
                    break
        history.append((state, distribution, action))
        selected |= 1 << action
    return selected, history


def train_one(workloads, seed, episodes):
    rng = random.Random(seed)
    feature_count = len(features("x y +", 0))
    weights = [[0.0] * feature_count for _ in FUSIONS]
    names = list(workloads)
    baseline = {name: statistics.mean(reward(workloads[name], mask) for mask in MASKS)
                for name in names}
    history = []
    for episode in range(episodes):
        name = names[rng.randrange(len(names))]
        workload = workloads[name]
        selected, decisions = select(workload["expression"], weights, rng)
        outcome = reward(workload, selected)
        advantage = max(-0.3, min(0.3, outcome - baseline[name]))
        baseline[name] = 0.99 * baseline[name] + 0.01 * outcome
        learning_rate = 0.045 / (1.0 + episode / episodes)
        for state, distribution, chosen in decisions:
            for action, chance in distribution.items():
                coefficient = learning_rate * advantage * ((action == chosen) - chance)
                for column, value in enumerate(state):
                    weights[action][column] += coefficient * value
        if (episode + 1) % 500 == 0:
            chosen_rewards = [reward(item, select(item["expression"], weights)[0])
                              for item in workloads.values()]
            history.append({"episode": episode + 1,
                            "mean_train_log_speedup": statistics.mean(chosen_rewards)})
    return {"seed": seed, "episodes": episodes, "weights": weights,
            "training_curve": history}


def train(episodes):
    data = read_measurements("train")
    models = [train_one(data["workloads"], seed, episodes) for seed in (7, 17, 27)]
    output = {"algorithm": "REINFORCE with moving per-workload baseline",
              "training_binary_sha256": data["binary_sha256"],
              "models": models}
    path = DATA / "models.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Trained {len(models)} policy-gradient seeds for {episodes} episodes each")
    return output


def greedy_mask(expression):
    state = features(expression, 0)
    ranked = sorted(range(len(FUSIONS)), key=lambda action: (-state[action + 1], action))
    return sum(1 << action for action in ranked[:CHOOSE])


def geometric_speedup(workloads, choices):
    return math.exp(statistics.mean(reward(workload, choices[name])
                                    for name, workload in workloads.items()))


def evaluate(split="final"):
    train_data = read_measurements("train")
    test_data = read_measurements(split)
    model_data = json.loads((DATA / "models.json").read_text(encoding="utf-8"))
    if model_data["training_binary_sha256"] != test_data["binary_sha256"]:
        raise RuntimeError("train and test used different VM binaries")
    training = train_data["workloads"]
    testing = test_data["workloads"]
    fixed_mask = max(MASKS, key=lambda mask: geometric_speedup(
        training, {name: mask for name in training}))
    methods = {
        "fixed_train_best": {name: fixed_mask for name in testing},
        "pair_frequency_greedy": {name: greedy_mask(item["expression"])
                                  for name, item in testing.items()},
        "initial_sweep_best_36_choices": {
            name: max(MASKS, key=lambda mask: reward(item, mask))
            for name, item in testing.items()},
    }
    for model in model_data["models"]:
        methods[f"policy_gradient_seed_{model['seed']}"] = {
            name: select(item["expression"], model["weights"])[0]
            for name, item in testing.items()
        }
    summary = {}
    for method, choices in methods.items():
        summary[method] = {
            "geometric_mean_speedup": geometric_speedup(testing, choices),
            "cases": {
                name: {"mask": mask, "fusion_names": [FUSIONS[action][2]
                        for action in range(len(FUSIONS)) if mask & (1 << action)],
                       "speedup": runtime(item, 0) / runtime(item, mask),
                       "baseline_ns_per_item": runtime(item, 0),
                       "chosen_ns_per_item": runtime(item, mask)}
                for name, item in testing.items()
                for mask in [choices[name]]
            },
        }
    output = {
        "question": "Can an RL policy select useful bytecode fusions for unseen expressions?",
        "evaluation_split": split,
        "train_programs": len(training), "test_programs": len(testing),
        "fusion_budget": CHOOSE, "candidate_sets": len(MASKS),
        "fixed_train_best_mask": fixed_mask,
        "methods": summary,
    }
    (DATA / f"{split}_results.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    for name, item in summary.items():
        print(f"{name}: {item['geometric_mean_speedup']:.3f}x geometric mean speedup")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("measure-train", "train", "measure-test",
                                          "measure-final", "measure-stress",
                                          "evaluate", "evaluate-stress", "all"))
    parser.add_argument("--count", type=int, default=500000)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--episodes", type=int, default=6000)
    arguments = parser.parse_args()
    if arguments.phase in ("measure-train", "all"):
        measure("train", arguments.count, arguments.repetitions)
    if arguments.phase in ("train", "all"):
        train(arguments.episodes)
    if arguments.phase in ("measure-test", "all"):
        measure("test", arguments.count, arguments.repetitions)
    if arguments.phase in ("measure-final", "all"):
        measure("final", arguments.count, arguments.repetitions)
    if arguments.phase in ("measure-stress", "all"):
        measure("stress", arguments.count, arguments.repetitions)
    if arguments.phase in ("evaluate", "all"):
        evaluate()
    if arguments.phase == "evaluate-stress":
        evaluate("stress")


if __name__ == "__main__":
    main()
