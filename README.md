# Moqi · 默契

**Auditable memory and learning for smart-home agents.**

[中文说明](README.zh-CN.md) · [Architecture & API](docs/framework.md) · [Playground](docs/playground.md) · [Contributing](CONTRIBUTING.md)

Moqi records what a home can actually observe, learns contextual habits from verified human actions, and keeps the evidence behind its understanding inspectable. A resident can correct a habit, limit an action, or restore an earlier understanding without erasing what happened.

**Initial developer preview, pre-1.0.** Hardware integration and real household evaluation are pending. No device-execution API is enabled. Model accuracy, energy savings and ITX latency have not been demonstrated. License selection is pending; no open-source license grant is included yet.

## Try a home that learns

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
| Language | Bounded correction rules; optional local EdgeJev adapter and real-model acceptance harness |
| Safety | Independent deterministic reviewer; no physical execution permission |
| Speech policy | Persistent occupancy/nighttime/daily-budget checks; audio pipeline not connected |

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

Non-Python adapters can use the [versioned JSON format](examples/observation.json) and `Observation.from_dict`. Home Assistant is the included read-only WebSocket adapter. Device contributors can start with contract tests and later attach redacted hardware evidence.

## EdgeJev is optional

Moqi uses [EdgeJev](https://github.com/yzfly/edgejev) for typed language interpretation, not as the numerical/time/safety controller. Model-only corrections require explicit acceptance until home-domain calibration. Missing runtime or model files produce explicit blocked results. The browser uses rules and does not pretend to run EdgeJev.

With the runtime installed and a local model directory:

```bash
python -m moqi.voice_benchmark --model /path/to/jev-int8 --output data/voice-report.json
```

This checks twelve text cases and measures actual routing/latency. It is not a household calibration study. Model weights and upstream distribution rights are separate from this repository.

## Develop and contribute

```bash
python -m unittest discover -s tests -v
```

Tests cover persistence, chronology, coverage, attribution, learning, rollback, parsing, safety faults and playground scenarios. CI configuration includes Python 3.11–3.14 and package builds; hosted CI has not run before publication.

Useful contributions include verified adapters, browser compatibility tests, model-equipped EdgeJev acceptance and chronological benchmark engines. Read [CONTRIBUTING.md](CONTRIBUTING.md). Do not submit databases, passwords, HA tokens, audio or model weights in issues or pull requests.

## Boundaries before deployment

The confirmed target is Ubuntu Server x86-64 on an ITX Celeron PC. Gateway compatibility, physical attribution, load classification, metering and performance need hardware acceptance. Mandatory-announcement requirements conflict with nighttime silence and speech budgets; execution stays disabled.

Raw inputs stay local. Retention is a program policy, not a forensic-erasure guarantee or deletion of user exports/backups. The browser is session-only; local deployment uses persistent SQLite and Git. No cloud model is enabled by default.
