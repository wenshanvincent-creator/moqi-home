# Contributing

Moqi is in developer review. Start with an issue describing the observed problem, input evidence and expected behavior. Small changes with an explicit acceptance boundary are easier to review than replacing the learning system.

## Local checks

Use Python 3.11+ and Git. From the repository root:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m tools.build_playground --output dist/playground/index.html
```

Use a new, isolated data directory for every synthetic replay. Never run demos against a household database. Do not commit local environments, `.env`, tokens, real logs, databases, model weights or deployment-specific identifiers.

## Device adapters

Follow `docs/framework.md` and `examples/adapter.py`. Describe supported state units, physical-button observability, automation sources, HA reconnect behavior and missing coverage. Human attribution must cite evidence. A sensor event or HA authenticated context is not sufficient by itself.

An adapter can be contributed with synthetic contract tests before hardware is available. Mark real device compatibility **unverified** until the contributor supplies an acceptance report with private information removed. Do not claim a gateway or smart plug supports every firmware version based on one test.

## Learning changes

Test evidence semantics rather than a copy of the new implementation. Important cases include unknown attribution, repeated events, chronological replay, missing coverage, restored memory, exposure-based forgetting and finite probabilities. Schema changes require explicit version/migration handling and tests using a prior database.

Preserve observations and operational ledgers during memory rollback. Language-model confidence never relaxes a safety invariant. Add model integration behind an optional adapter; preserve rules and explicit missing-artifact errors.

## Playground changes

Live results must come from the Python engine. Recorded fixtures must be generated and labeled as recorded. Never turn synthetic evidence into a reported household result. Test keyboard navigation, narrow screens, reset/rollback and runtime loading failures before describing a browser release as validated.

## Attribution and licensing

Identify third-party code, models, datasets and their licenses. Model weights have separate distribution terms. The project license is selected before public release; current review artifacts do not infer permission from an unapproved license draft.
