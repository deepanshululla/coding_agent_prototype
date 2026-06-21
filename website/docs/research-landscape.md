---
sidebar_position: 17
title: Research Landscape
description: Where this project sits in the 2026 coding-agent research landscape — what is and isn't publishable, and how the pluggable architectures + eval harness form a controlled-experiment rig.
---

# Research Landscape

This is a learning project, not a research artifact — but the questions "is any of this
publishable?" and "what is the state of the art actually doing?" came up, and the answers are
worth recording. This page is an **honest map** of where a from-scratch coding agent sits in the
mid-2026 research landscape, what is and isn't a real contribution, and how the project's existing
seams happen to form a usable experiment rig.

It is written in the same spirit as [Differences from pi.dev](./differences-from-pi.md): tell the
truth about scope rather than oversell.

---

## The honest bottom line

**A "coding agent from scratch" is not, by itself, publishable.** That space is saturated. Every
major lab and dozens of academic groups ship one, and the headline benchmark (SWE-bench Verified)
has moved from ~75% to ~89% within 2025–2026. "I reimplemented the agent loop" is a great way to
*learn*, not a contribution.

**What is publishable is a measurement** — a small, controlled, honest empirical study. The field
has largely shifted from "build a better agent" to "decompose and measure what makes agents work."
A single researcher with a clean, controllable harness can contribute there, and this project's
harness is unusually well-suited to it (see [The rig](#the-rig-we-accidentally-built) below).

---

## What the SOTA is doing (mid-2026)

Four live threads, all of which this project touches:

| Thread | What it argues | Representative work |
|---|---|---|
| **Harness ≠ model** | Agent scores must be attributed to the *model-harness pair*, not the model. The scaffold (context mgmt, tools, recovery, budget) is a first-class variable currently conflated with model capability. | Harness-Bench (arXiv 2605.27922); "Code as Agent Harness" (arXiv 2605.18747) |
| **Do skills/configs actually help?** | Empirically *mixed* — many skills and config files are marginal once you account for the context cost they add. | SWE-Skills-Bench (arXiv 2603.15401); "On the Impact of AGENTS.md Files" (arXiv 2601.20404); "Configuring Agentic AI Coding Tools" (arXiv 2602.14690) |
| **Memory & self-improvement** | Persistent/episodic memory and on-the-fly self-evolution. Hot, but increasingly needs RL infra and compute. | MemRL; MemEvolve; Live-SWE-agent (arXiv 2511.13646); Structurally Aligned Subtask-Level Memory (arXiv 2602.21611) |
| **Eval / grader reliability** | LLM-as-judge graders need calibration against human labels (Cohen's κ) and bias controls (position, verbosity, self-preference). | Reliability-aware judge frameworks (arXiv 2604.27727); rubric-refinement work |

The throughline: **attribution**. A score measures not what the model can infer, but what the
*harness lets it observe, modify, recover from, and verify*. That is the gap a controllable
from-scratch harness can speak to.

---

## The rig we accidentally built

Two existing seams, neither novel on its own, combine into something the big benchmarks struggle to
do cleanly:

1. **Pluggable control-flow architectures** — `reactive`, `orchestrator-worker`,
   `evaluator-optimizer`, `planner-executor`, all behind one `--architecture` flag
   (`src/architecture.py`, `src/architectures/`; see
   [Strategy Pattern](./architecture-patterns/strategy-pattern.md) and
   [Planner / Executor](./architecture-patterns/planner-executor.md)).
2. **A token-aware eval harness** — deterministic graders (pytest / command / file-contains) with
   per-task **token totals** and isolated temp workdirs (`evals/harness.py`, `evals/graders.py`,
   `evals/suites/`).

Together they let you **hold the model and tasks fixed, vary only the scaffold, and read off both
success rate and token cost.** Most papers can't isolate the scaffold this cleanly because their
control flow is welded to one strategy. Here it's a one-flag swap with cost already instrumented.

:::caution Be honest about what's novel
The four control-flow patterns are *not* a contribution — they are the named patterns from
Anthropic's "Building Effective Agents," and LangGraph / AutoGen already let you swap them. The
contribution would be the **measurement** (a controlled cost-benefit comparison on identical
tasks and model), never the architecture system itself. And even the measurement is partly done:
[Benchmarking Multi-Agent LLM Architectures](https://arxiv.org/abs/2603.22651) (2026) compares
sequential / parallel-fan-out / hierarchical-supervisor / reflexive-self-correcting on
cost-accuracy axes and finds the reflexive loop most accurate at **2.3× the cost** of the
sequential baseline — exactly the Pareto-frontier shape proposed here, but for *financial
document extraction*, not code. The remaining gap is doing it for **coding tasks with
executable, hidden-test graders** (see [Where the gaps are](#where-the-gaps-are)).
:::

---

## Publishable angles, ranked

| Rank | Angle | Fit to this repo | Main effort | Novelty risk |
|---|---|---|---|---|
| **Best** | Control-flow cost-benefit study: success-rate × token-cost Pareto frontier across architecture × model × task | Excellent — rig already exists | Need a real task set + multiple seeds | Low, if framed as measurement |
| Good | Skill / memory / `CLAUDE.md` ablation: does each context layer pay for the tokens it adds? | Good — skills + memory seams exist | Same — real tasks + seeds | Low |
| Skip | "A pluggable agent-architecture system" as a system paper | — | — | High — not novel |

**Realistic venue:** a workshop or preprint (e.g. the ICSE AGENT workshop, or arXiv), not a top
conference. The accepted genre there is exactly "one researcher, controlled study, honest mixed
results."

---

## Where the gaps are

The 2026 literature is dense, so the honest exercise is finding what it *hasn't* covered. Cross-
referencing the threads above against this project's seams, five gaps stand out — roughly ordered
by how well this rig could hit them:

1. **Architecture cost-benefit, for code specifically.** The architecture-comparison method already
   exists ([2603.22651](https://arxiv.org/abs/2603.22651)) — but on financial-document F1, not on
   executable code. Nobody has cleanly run *reactive vs. planner-executor vs. orchestrator-worker
   vs. evaluator-optimizer* on coding tasks with **pass/fail hidden-test graders**, model held
   fixed. The grader being executable (not a judge or an F1) is the whole point: it removes the
   measurement noise the financial study carries. **This rig is built for exactly this.**

2. **The architecture × context-layer cross-term.** The ablation papers
   ([AGENTS.md](https://arxiv.org/abs/2601.20404), [SWE-Skills-Bench](https://arxiv.org/pdf/2603.15401))
   hold the *architecture* fixed and vary skills/configs. The architecture papers hold *context*
   fixed and vary control flow. **Nobody studies the interaction**: does an orchestrator-worker —
   which re-derives context per subtask — depend on `CLAUDE.md` / skills *less* than a flat
   reactive loop? This project is one of the few harnesses with both axes swappable, so the
   cross-term is reachable here and almost nowhere else.

3. **Reproducible cost accounting on a minimal harness.** [Harness-Bench](https://arxiv.org/abs/2605.27922)
   and [Claw-SWE-Bench](https://arxiv.org/html/2606.12344v1) (June 2026) make cost a first-class
   axis, but at benchmark scale with heavy infra. A *fully transparent, laptop-runnable* harness —
   deterministic graders, no API cost for grading, token estimate as plain `len(json)//4` — is
   itself underserved. "Honest cost-benefit you can reproduce in an afternoon" is a real niche.

4. **Failure-by-architecture taxonomy.** [Token Budgets](https://arxiv.org/abs/2606.04056) (June
   2026) catalogs 63 budget-overrun incidents but framework-agnostic. *Which control-flow patterns
   cause runaway spend* — orchestrator nesting, critic loops that never converge — is unmapped. The
   compaction ladder ([Context Compaction](./advanced/compaction.md)) and depth caps in this repo
   are the instrumentation to study it.

5. **Long-horizon degradation by architecture.** [SlopCodeBench](https://arxiv.org/pdf/2603.24755)
   shows agents degrade over long iterative tasks, but framework-wide. *Does planner-executor
   degrade slower than reactive over a 20-step task?* Architecture × horizon is open.

6. **Language-specialized tools — measured, not just shipped.** Unlike the others, this is *mostly
   solved at the capability level*, and it's worth recording precisely so. Purpose-built,
   language-aware tools were the original SWE-agent contribution
   ([the Agent-Computer Interface](https://arxiv.org/abs/2405.15793): windowed file viewer,
   `find_file`, lint-before-apply edits — 3.8% → 12.5% on SWE-bench). Today, LSP-backed tools
   (rust-analyzer, Pyright, gopls) and compiler-in-the-loop diagnostics are *standard* in
   production agents, and [RLCSF](https://arxiv.org/abs/2510.22907) even trains on
   compiler/language-server reward. So "add language-specific dev tools" is **not** a green field.
   The honest opening is **attribution**: how much does each language tool buy you, per language,
   on a fixed model with executable graders and at what token cost — and does a Rust-aware toolset
   (parsed `cargo` / borrow-checker feedback) close the Python→Rust gap *without* model
   fine-tuning? The generic 7-tool baseline ([Adding a Tool](./tools/adding-a-tool.md)) is a clean
   substrate to add one language pack onto and read off the delta.

Gaps **1** and **2** are the sweet spot: both are reachable with the seams that already exist, and
**2** in particular is something most published rigs structurally *cannot* do, because their
control flow and their context layer aren't independently swappable. Gap **6** is the most
*crowded* — the tools themselves are well-trodden — so its only honest contribution is
measurement, not novelty.

## The gap between rig and result

The rig's *design* supports a real study; its *content* does not yet. Two honest gaps stand
between this project and a paper:

- **Task scale.** `evals/suites/smoke.py` is three toy tasks (`add-function`, `fix-bug`,
  `count-lines`) — a smoke test, not a benchmark. SWE-Skills-Bench used 14 tasks and that is
  already thin. A study needs a real set: a SWE-bench-Lite subset, or 30–50 self-contained tasks
  with hidden-test graders.
- **Statistical rigor.** Multiple seeds per cell, reported variance, and a reproducible harness
  (pinned model, logged trajectories). The harness already tracks tokens and isolates workdirs;
  the missing piece is *running it at scale and reporting it carefully*.

Both gaps are **additive work on top of the existing seams**, not a redesign — which is the whole
reason this is worth recording rather than dismissing.

---

## Sources

The SOTA survey behind this page drew on the following. Dates are from the arXiv IDs (`YYMM`),
newest first within each group.

**Harness as a first-class variable**

- [Claw-SWE-Bench: Evaluating OpenClaw-style Agent Harnesses on Coding Tasks](https://arxiv.org/html/2606.12344v1) — Jun 2026; harness + cost as first-class axes, 350 issues across 8 languages.
- [Harness-Bench: Measuring Harness Effects across Models in Realistic Agent Workflows](https://arxiv.org/abs/2605.27922) — May 2026.
- [Code as Agent Harness](https://arxiv.org/abs/2605.18747) — May 2026.

**Architecture / control-flow cost-benefit** (the closest prior work to angle #1)

- [Benchmarking Multi-Agent LLM Architectures for Financial Document Processing](https://arxiv.org/abs/2603.22651) — Mar 2026; sequential vs. parallel vs. hierarchical vs. reflexive, cost-accuracy tradeoffs.
- [Token Budgets: An Empirical Catalog of 63 LLM-Agent Budget-Overrun Incidents](https://arxiv.org/abs/2606.04056) — Jun 2026.
- [Token Economics for LLM Agents: A Dual-View Study](https://arxiv.org/html/2605.09104v1) — May 2026.

**Do skills / configs / context layers help?**

- [SWE-Skills-Bench: Do Agent Skills Actually Help in Real-World Software Engineering?](https://arxiv.org/pdf/2603.15401) — Mar 2026.
- [On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents](https://arxiv.org/html/2601.20404v2) — Jan 2026.
- [Configuring Agentic AI Coding Tools: An Exploratory Study](https://arxiv.org/pdf/2602.14690) — Feb 2026.

**Language specialization: benchmarks, models & tools**

- [SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://arxiv.org/abs/2405.15793) — May 2024; the foundational "language-aware tools matter" result.
- [Reinforcement Learning from Compiler and Language Server Feedback (RLCSF)](https://arxiv.org/abs/2510.22907) — Oct 2025; compiler/LSP signals as training reward.
- [Building Effective AI Coding Agents for the Terminal: Scaffolding, Harness, Context Engineering](https://arxiv.org/pdf/2603.05344) — Mar 2026.
- [Evaluating and Improving Automated Repository-Level Rust Issue Resolution with LLM-based Agents](https://arxiv.org/html/2602.22764v1) — Feb 2026 (Rust-SWE-bench).
- [From SWE-ZERO to SWE-HERO: Execution-based Fine-tuning for SE Agents](https://arxiv.org/pdf/2604.01496) — Apr 2026; Python-trained, transfers cross-language.
- [From Translation to Superset: Benchmark-Driven Evolution of a Production AI Agent from Rust to Python](https://arxiv.org/html/2604.11518v1) — Apr 2026.

**Evaluation, degradation, and self-improvement**

- [SlopCodeBench: How Coding Agents Degrade Over Long-Horizon Iterative Tasks](https://arxiv.org/pdf/2603.24755) — Mar 2026.
- [SWE Atlas: Benchmarking Coding Agents Beyond Issue Resolution](https://arxiv.org/html/2605.08366v1) — May 2026.
- [Live-SWE-agent: Can Software Engineering Agents Self-Evolve on the Fly?](https://arxiv.org/pdf/2511.13646) — Nov 2025.
- [LLM-as-a-Judge for Human-AI Co-Creation: A Reliability-Aware Evaluation Framework](https://arxiv.org/html/2604.27727v1) — Apr 2026.
- [Evaluation and Benchmarking of LLM Agents: A Survey](https://arxiv.org/pdf/2507.21504) — Jul 2025.
