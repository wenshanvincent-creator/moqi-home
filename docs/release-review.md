# Personal repository release review

Updated 2026-10-22 for the software-preparation milestone. The detailed scope and open field gates are recorded in the [acceptance ledger](jev-memory-acceptance.md).

The repository is **moqi-home**, intended for the owner's personal GitHub account. Its initial scope is a developer preview. Publication of the source does not imply completion of the acceptance checks below.

The agreed audience is smart-home developers. The first playground's main story is a synthetic household forming habits, receiving corrections, losing confidence through covered missed opportunities, becoming dormant without context, and restoring earlier understanding. Hardware contributors can connect observations through a versioned contract before collecting real household data.

## Review what exists

1. Read the bilingual README and `docs/framework.md` for scope, interfaces and limitations.
2. Open `dist/playground/index.html` and navigate the ten labeled recorded states. Try live mode on a working browser and network; its acceptance is still pending.
3. Inspect `examples/adapter.py`, `examples/observation.json` and the core/playground tests. Unknown attribution and disconnected coverage must stay explicit.
4. Review the optional EdgeJev boundary. The browser uses rules; a real model report requires local runtime and weights.
5. Local review exports carry a `REVIEW-MANIFEST.json` with selected source hashes. Household databases, credentials, recordings, private deployment documents and model caches are excluded from repository preparation.

## Evidence and open gates

| Check | Current evidence |
|---|---|
| Core and scenario suite | 190 local CPython checks passed, followed by 14 targeted checks including a later permission-revocation case; four complete synthetic behavior scenarios passed |
| Playground build | Nineteen core source files and ten engine-generated states embedded |
| JavaScript | Main/worker syntax and embedded source hashes checked |
| Python distribution | Wheel build is configured in CI; this publication checks the exported source and CLI contracts |
| Privacy boundaries | Explicit export selection and known credential/path scan |
| Hosted CI | [Core and package checks](https://github.com/wenshanvincent-creator/moqi-home/actions/workflows/tests.yml) (`.github/workflows/tests.yml`) succeeded on `main` for the pushes on 2026-10-03 and 2026-10-22 (Python 3.11–3.14, unit tests, playground build, package build). This row does not claim a result for later commits |
| Live WebAssembly and browser interaction | Eight command classes passed with actual Python + SQLite under Pyodide 314.0.7; real browser interaction remains pending |
| Hardware, EdgeJev model and audio | Pending; no physical execution enabled |
| License | Pending owner choice; no final license grant included |

The owner has authorized publication of the software-preparation changes. License selection, browser interaction, and static playground hosting remain follow-up work. They are required before claiming a licensed open-source release or an accepted live demonstration. Hosted CI succeeded on `main` on 2026-10-03 and 2026-10-22; that success does not license the project or accept a live demonstration, and a later commit can still fail its own run. Repository publication alone is not evidence that any of these checks passed. Cloud requests, real model inference and physical execution were not used for the local checks.

## Hardware follow-up

Real household acceptance remains separate from the synthetic demo: verify the HA/gateway connection, device state reporting, attribution, observation coverage, load classification and metering. Energy savings, model accuracy and ITX latency require measured evidence. A required announcement that cannot satisfy occupancy, nighttime silence or speech budgets prevents dispatch; it is not silently omitted. Execution remains off by default.
