# Personal repository release review

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
| Core and scenario suite | 103 local CPython tests pass; exported source tested independently |
| Playground build | Twelve core source files and ten engine-generated states embedded |
| JavaScript | Main/worker syntax and embedded source hashes checked |
| Python distribution | Pure-Python wheel built; separate import smoke check |
| Privacy boundaries | Explicit export selection and known credential/path scan |
| Hosted CI | Configuration prepared; no GitHub run yet |
| Live WebAssembly and browser interaction | Pending; local Windows runtime failures prevent acceptance here |
| Hardware, EdgeJev model and audio | Pending; no physical execution enabled |
| License | Pending owner choice; no final license grant included |

The owner has chosen to publish this initial source preview and complete remaining checks afterward. License selection, live browser/WASM acceptance, hosted CI results and static playground hosting remain follow-up work. They are required before claiming a licensed open-source release or an accepted live demonstration. Repository publication alone is not evidence that any of these checks passed.

## Hardware follow-up

Real household acceptance remains separate from the synthetic demo: verify the HA/gateway connection, device state reporting, attribution, observation coverage, load classification and metering. Energy savings, model accuracy and ITX latency require measured evidence. The original application's mandatory announcement requirement conflicts with nighttime silence and speech budgets; resolve that policy before enabling physical execution.
