# Experiment record

## Question

Can a policy-gradient agent trained on measured performance of 12 bytecode programs select two fusions for unseen programs more effectively than a simple frequency rule? The work is an exploratory one-day pilot. The protocol was refined during development, including masking fusion rules absent from a program. The four manually written final expressions and 20 generated stress expressions were then evaluated without further policy changes. This is not a preregistered study or a claim of a novel algorithm.

## System

The source language is a restricted reverse Polish expression over `x`, `y`, nonnegative integer constants, addition, subtraction, and multiplication. The compiler validates stack depth and translates tokens to bytecode. Nine fusion rules can combine a particular adjacent pair of original instructions into one interpreter instruction. The chosen set is applied in a single left-to-right pass. Two rules may overlap, so their effects are not always additive. Arithmetic uses unsigned 64-bit wraparound, which is well-defined in C++.

The C++ runtime executes the bytecode with a stack. It checks every candidate against unfused execution on 1,024 deterministic random input pairs before timing. The executable's `--self-test` checks known answers and all 512 possible fusion masks on five expressions. For each measured workload, the harness also requires matching full-run checksums across all 36 two-rule choices and the unfused baseline. All checks passed.

## Agent and alternatives

The agent sees pair frequencies in the original bytecode, which rules it has already selected, and program length. It selects two rules in sequence. Rules absent from the program are masked out. The reward is the log ratio of unfused to fused median time per item. Three linear softmax policies are trained with REINFORCE and a moving reward baseline, each for 6,000 episodes with seeds 7, 17, and 27. The RL trainer queries a table of prior measurements for the 12 training programs; it makes no new hardware measurement during those episodes. Creating that table required 12 x 37 = 444 measured configurations. This offline data cost is part of the method's cost.

The frequency rule selects two adjacent pairs with the highest raw counts, breaking ties by fixed rule order. The fixed-rule baseline picks one pair of fusion rules that has the best geometric mean training performance and uses it for all new programs. Both RL and the fixed-rule baseline use the same training measurements; the frequency rule needs none. An initial sweep of all 36 choices on each evaluation program provides a reference selected with 36 evaluations per program. That reference is not a zero-shot competitor or a true performance ceiling: independent remeasurement can change which choice appears best.

## Workloads and measurements

The training set contains 12 hand-written arithmetic expressions. A four-expression development set was inspected while correcting the action-mask design, so it is not used as the final evidence. Four additional expressions were written and frozen as a final set. A deterministic generator with seed 20261028 created 20 longer stress expressions. The source expressions and split assignments are recorded in `scripts/experiment.py` and each data file. Manual choice of the train/final examples limits claims of generalisation.

The initial sweep measures 500,000 input pairs, one warm-up pass, then five timed repetitions per candidate. The C++ executable reports the median nanoseconds per input pair. A later confirmation remeasures only frozen method choices, interleaved in seeded random order, with three independent rounds and seven timed repetitions per round. The confirmation uses 2,000,000 pairs for the four-expression set and 1,000,000 pairs for the stress set. Inputs are generated deterministically outside the timed region. All methods for a workload use the same input sequence and same compiled executable.

The compiler was Microsoft Visual C++ 14.50.35717 with `/O2`, C++17, on the Intel-compatible machine reported by Windows. Each measurement file records the executable SHA-256 and platform string. Rebuilding can produce a different hash, in which case the runner refuses to combine the new executable with saved measurements. This measures this machine's software, not an Arm CPU or a hardware design.

## Confirmed results

The figures are geometric means of per-expression runtime ratios against unfused interpretation. They are independent confirmation results, not the first sweep used to train or select policies.

| Method | Four final expressions | 20 stress expressions |
| --- | ---: | ---: |
| Fixed training-set choice | 1.105x | 1.028x |
| Pair-frequency rule | 2.145x | 1.184x |
| RL seed 7 | 2.118x | 1.188x |
| RL seed 17 | 2.118x | 1.185x |
| RL seed 27 | 2.118x | 1.192x |
| Best choice from initial 36-choice sweep | 2.118x | 1.196x |

The learned policies are close to the cheap frequency rule. On the four final examples they do not improve the geometric mean. On the larger stress set the differences are under one percentage point in speedup ratio. These runs do not support a meaningful RL advantage. The initial sweep's best choice is occasionally beaten on confirmation because the original rankings contain measurement noise. We therefore do not interpret that row as a true optimum.

Fusion helps the interpreter on many examples, but the exact speedup depends on the bytecode pattern and timing conditions. A smaller instruction count is consistent with reduced interpreter dispatch, but this experiment does not isolate dispatch from code layout, branch prediction, or other compiler and CPU effects.

## Reproduce and inspect

Build the VM and run `--self-test` using the commands in the README. Then run the phases in this order: `measure-train`, `train`, `measure-test`, `measure-final`, `measure-stress`, `evaluate`, `evaluate-stress`, followed by `confirm.py` for `final` and `stress`. `experiment.py all` combines the first six phases through final evaluation. The train, development, final, and stress measurement JSON files preserve every attempted mask, its instruction counts, timing and checksum. `models.json` contains all policy weights and training curves. The result and confirmation JSON files preserve every selected rule and every independent timing sample.

Limitations: the language is tiny, workloads are synthetic, the sample of programs is small, the policy is linear, and a two-rule action space is modest. Training uses a complete measured table, so it does not demonstrate low-data RL. The experiment does not measure compiler construction overhead, energy, Arm performance, or production workload behaviour. It shows an end-to-end compiler, interpreter, and RL workflow with transparent evidence, and it identifies a strong simple baseline for a larger follow-up.
