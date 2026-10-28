# Learned bytecode fusion: a one-day compiler and RL study

This small project asks whether reinforcement learning can choose useful instruction fusions for a bytecode interpreter. It contains a custom compiler, a C++ runtime, and a trained policy-gradient agent. The result is an exploratory research prototype, not a production compiler or a new fusion algorithm.

## The idea in one minute

The input language uses reverse Polish notation. For example, `x 3 * y +` means `3*x + y`. The compiler translates it into five bytecode instructions: load `x`, load `3`, multiply, load `y`, add. The runtime executes those instructions for many pairs of values. A fusion such as `constant+multiply` combines two adjacent bytecode instructions into one. That can reduce interpreter dispatch work, but two possible fusions may overlap, so a two-fusion budget requires a choice.

The agent observes which adjacent instruction pairs occur in a program. It chooses two legal fusion rules, one after the other. The compiler rewrites the bytecode, then the C++ interpreter executes it. Training rewards measured speedup relative to the unfused program. The agent uses REINFORCE, a simple policy-gradient RL method. It was trained with three fixed random seeds on measurements from 12 expressions. The Python training code uses only the standard library.

```text
Expression -> bytecode compiler -> optional fusion pass -> C++ interpreter -> measured runtime
                                       ^
                                RL chooses two rules
```

The compiler is our own small compiler. This version does not use LLVM or a JIT. The interpreter is a language runtime. These are narrow examples of the three experience areas in the [Huawei ML Systems & Compilers description](https://huaweiuk.teamtailor.com/jobs/8364758-research-engineer-ml-systems-compilers-contractor), not a claim of production-level experience.

## Result

We compared the learned policies with a rule that selects the two most frequent adjacent instruction pairs. Speedup is relative to the same expression without fusion. The figures below come from independent, interleaved confirmation runs on one Intel machine. All evaluated fusion choices passed output checks.

| Method | Four held-out expressions | 20 fixed-seed generated expressions |
| --- | ---: | ---: |
| Frequency rule | 2.15x | 1.18x |
| RL seed 7 | 2.12x | 1.19x |
| RL seed 17 | 2.12x | 1.19x |
| RL seed 27 | 2.12x | 1.19x |

Numbers are geometric means across expressions, rounded to two decimals. The small differences between RL and the frequency rule are sensitive to benchmark noise and this limited workload set. **This pilot does not establish that RL is better.** It does show that the compiler transformation works and that a trained policy can choose useful fusions for expressions outside its training set. The full data and per-expression results are in [`data/`](data/); the methods and limitations are in the [experiment report](docs/experiment.md).

## Run it

Requirements: Python 3.12 or another recent Python 3, and a C++17 compiler. On Windows, Visual Studio with the C++ tools is used. On Linux or macOS, `build.sh` invokes `c++`. The Linux/macOS build path has not been verified on this machine.

Windows:

```powershell
cmd /c build.bat
.\build\fusion_vm.exe --self-test
.\build\fusion_vm.exe --expr "x 3 * y +" --mask 2 --count 100000 --repetitions 5
python scripts\experiment.py all
python scripts\experiment.py evaluate-stress
python scripts\confirm.py --split final
python scripts\confirm.py --split stress
```

Linux or macOS:

```bash
bash build.sh
./build/fusion_vm --self-test
python3 scripts/experiment.py all
python3 scripts/experiment.py evaluate-stress
python3 scripts/confirm.py --split final
python3 scripts/confirm.py --split stress
```

`--mask 2` enables the `constant+multiply` fusion in the example. A rebuild changes the binary hash, so rerun measurement and training phases before evaluating. The checked-in raw data belongs to the binary hash recorded in each measurement file.

## Where to look

- [`src/vm.cpp`](src/vm.cpp): expression compiler, fusion pass, interpreter, correctness checks, and timing.
- [`scripts/experiment.py`](scripts/experiment.py): workload splits, measurements, REINFORCE training, and comparisons.
- [`scripts/confirm.py`](scripts/confirm.py): fresh interleaved measurements of frozen choices.
- [`docs/experiment.md`](docs/experiment.md): the exact research question, protocol, interpretation, and limitations.

## Context

Instruction fusion, also called a *superinstruction*, is an established interpreter technique. The [eJSTK study](https://www.jstage.jst.go.jp/article/ipsjjip/27/0/27_658/_article) is one example. RL for compiler decisions is also established, including Google's [MLGO](https://research.google/blog/mlgo-a-machine-learning-framework-for-compiler-optimization/). This project tests their intersection in a deliberately small and inspectable system. The related [CPU design search project](https://github.com/HassanAlhajAli/cpu-design-search) investigates hardware settings in gem5 rather than changing software bytecode.

## AI-assisted development

Codex assisted with the initial implementation, measurements, and documentation. The raw evidence and checks are included so the work can be reviewed and reproduced. Hassan's own review and any revisions will appear in later commits.
