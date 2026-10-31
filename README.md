# Moqi · 默契

**Auditable memory and learning for smart-home agents (Home Assistant) — pre-1.0, shadow by default.**

[![Core and package checks](https://github.com/wenshanvincent-creator/moqi-home/actions/workflows/tests.yml/badge.svg)](https://github.com/wenshanvincent-creator/moqi-home/actions/workflows/tests.yml)

[中文说明](README.zh-CN.md) · [Architecture & API](docs/framework.md) · [Playground](docs/playground.md) · [Contributing](CONTRIBUTING.md)

Moqi records what a home can actually observe, learns contextual habits from verified human actions, and keeps the evidence behind its understanding inspectable. A resident can correct a habit, limit an action, or restore an earlier understanding without erasing what happened.

**Software preparation, pre-1.0.** The integrated runtime defaults to shadow mode. HA owns device selection and the final dispatch boundary; hardware integration and real household evaluation remain pending. Model accuracy, energy savings and ITX latency have not been demonstrated. License selection is pending; no open-source license grant is included yet.

Habits come from Home Assistant observations and local learning, not from EdgeJev. Deterministic code handles numeric and time decisions first. Optional local [EdgeJev](https://github.com/yzfly/edgejev) covers only unresolved supported language. Optional nightly DeepSeek reflection can propose background updates inside a US$1 monthly estimated budget, and it stays off unless `reflection.enabled` is set. Optional household interaction is voice, with complete silence from 23:00 to 07:00. When live dispatch is explicitly enabled and HA has also selected the device, the current scope is earned low-risk lights. HVAC and other devices can be learned and shadowed; they are not auto-executed in this scope.

## Try in 2 minutes

Python 3.11 or newer. From a checkout of this repository:

```bash
python -m pip install -e .
python -m moqi.scenarios --directory data/software-replay-001
python -m tools.build_playground --output dist/playground/index.html
```

The scenario command replays chronological synthetic behavior with no model, cloud, Home Assistant, or audio device. Open `dist/playground/index.html` for the recorded walkthrough; it does not need a server. Select **Start live sandbox** only if you want the same learning core in the browser through Pyodide (startup downloads need internet; browser acceptance is still pending).

A short playground GIF is welcome at `docs/media/playground.gif`. No GIF is in the repository yet.

Optional synthetic system demo. Use a new directory; do not point it at a household database:

```bash
python -m moqi.demo --output data/system-demo
```

## Prepare the software before hardware

```bash
python -m pip install -e .
python -m moqi.scenarios --directory data/software-replay-001
```

This runs chronological, synthetic behavior scenarios without a model, cloud, HA or audio device. Counts and trust are computed from the event streams. See the [acceptance ledger](docs/jev-memory-acceptance.md), [software boundaries](docs/software-preparation.md), [Ubuntu steps](docs/ubuntu-software-install.md) and [server model/audio setup](docs/model-and-audio-setup.md). Source bundles do not include HA images or model weights.

## Developer playground

```bash
python -m pip install -e .
python -m tools.build_playground --output dist/playground/index.html
```

Open `dist/playground/index.html`. Its recorded walkthrough works without a server. Select **Start live sandbox** to run the same Python learning core and SQLite locally in your browser through Pyodide. Startup downloads require internet. Browser compatibility acceptance is still pending; failures leave the recorded walkthrough available and labeled.

Observe several days of turning on a dining lamp, skip the routine, add an unknown-cause event, simulate an undo, set a Chinese prohibition and restore understanding. Inspect α/β evidence, context strata, trust and the diary. All data is synthetic; no HA instance, cameras or API keys are involved. See [playground details and acceptance status](docs/playground.md).

## What is implemented

| Component | Behavior |
|---|---|
| Observations | Allowlisted events, event-time normalization, deduplication and explicit attribution |
| Structured memory | SQLite events, episodes, contextual habits, evidence, questions and world models |
| Learning | Exposure-based forgetting, dormancy, shadow feedback, undo/correction feedback and earned trust |
| Understanding | Editable local Markdown/YAML, dedicated Git history and memory-only rollback |
| Language | Code-first interpretation; bounded local EdgeJev context; versioned policy validation/shadow/rollback |
| Background | Local daily journal/thermal work; deidentified DeepSeek summaries, token/cache accounting and persistent budgets |
| Safety | Independent reviewer, HA-owned scope, reserved command IDs and observed-state reconciliation; shadow by default |
| Speech | In-memory wake/VAD/ASR/TTS adapters, spoken confirmation, occupancy/nighttime/budget checks; real audio unverified |

Four verified occurrences can seed a candidate, but observation is not execution approval. Unknown actuator changes remain unknown. Motion stopping is not proof of an empty room. Language-model confidence does not override safety.

## Connect your observations

Python 3.11+ is required. Full local L3 versioning also requires Git.

```python
from datetime import datetime, timedelta, timezone
from moqi import HomeMemory, Observation

config = {
    "site": "example-home", "timezone": "Asia/Shanghai",
    "entities": {"switch.lamp": {
        "role": "actuator", "room": "dining", "risk": "low", "category": "light"
    }}
}
at = datetime(2026, 3, 2, 10, tzinfo=timezone.utc)
with HomeMemory(config, "data/example.sqlite3") as memory:
    memory.ingest(Observation("switch.lamp", at, "off"))
    memory.ingest(Observation(
        "switch.lamp", at + timedelta(minutes=5), "on", "off",
        source="human", evidence="Synthetic example; replace with verified physical evidence"
    ))
    memory.observe_interval(at, at + timedelta(minutes=30))
    memory.learn(at + timedelta(minutes=31))
    print(memory.inspect(at + timedelta(minutes=31))["habits"])
```

One example does not establish a habit. Use a fresh database for demos. Real adapters must verify attribution and coverage; the framework cannot independently prove contributor labels.

Non-Python adapters can use the [versioned JSON format](examples/observation.json) and `Observation.from_dict`. HA events remain read-only observations; the separate custom integration owns selected-device dispatch. Device contributors can start with contract tests and later attach redacted hardware evidence.

## EdgeJev is optional

Moqi uses [EdgeJev](https://github.com/yzfly/edgejev) for typed language interpretation. Numerical/time/safety decisions stay in code. Model-only corrections require spoken confirmation; ordinary habit learning requires no teaching or webpage approval. Missing runtime or model files produce explicit blocked results. The browser uses rules and does not pretend to run EdgeJev.

With the runtime installed and a local model directory:

```bash
python -m moqi.voice_benchmark --model /path/to/jev-int8 --output data/voice-report.json
```

This checks twelve text cases and measures actual routing/latency. It is not a household calibration study. Model weights and upstream distribution rights are separate from this repository.

## Develop and contribute

```bash
python -m unittest discover -s tests -v
```

Tests cover persistence, chronology, coverage, attribution, learning, rollback, parsing, safety faults and playground scenarios. The hosted workflow [Core and package checks](https://github.com/wenshanvincent-creator/moqi-home/actions/workflows/tests.yml) (`.github/workflows/tests.yml`) has succeeded on `main`, including the pushes on 2026-10-03 and 2026-10-22. It runs Python 3.11–3.14, the unit tests, the playground build, and the package build. The badge tracks the default branch; it does not promise that a later commit or pull request passed.

Useful contributions include verified adapters, browser compatibility tests, model-equipped EdgeJev acceptance and chronological benchmark engines. Read [CONTRIBUTING.md](CONTRIBUTING.md). Do not submit databases, passwords, HA tokens, audio or model weights in issues or pull requests.

## Boundaries before deployment

The confirmed target is Ubuntu Server x86-64 on an ITX Celeron PC. Gateway compatibility, physical attribution, load classification, metering and performance need hardware acceptance. Mandatory-announcement requirements conflict with nighttime silence and speech budgets; execution stays disabled.

Raw inputs stay local. Retention is a program policy, not a forensic-erasure guarantee or deletion of user exports/backups. The browser is session-only; local deployment uses persistent SQLite and Git. No cloud model is enabled by default.
