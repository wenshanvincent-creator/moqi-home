# Playground: living in a synthetic home

Build from the repository root:

```bash
python -m tools.build_playground --output dist/playground/index.html
```

Open the generated HTML in a modern browser. The recorded walkthrough is embedded and works without a server or model downloads. It consists of ten states generated from the real engine and is explicitly labeled **Recorded walkthrough**. Its controls navigate recorded steps; they do not run new learning.

Choose **Start live sandbox** for interactive learning. It loads Pyodide 314.0.7 and tzdata, mounts the bundled Python sources, and creates an isolated SQLite database in a module worker. No server-side Python service, HA instance or cloud key is required. A Worker/CORS/CDN failure keeps the recorded walkthrough available with the error shown.

If local file permissions prevent the runtime loading, the intended deployment is a static web host, such as GitHub Pages. To serve a local review with the standard library:

```bash
python -m http.server 8878 --bind 127.0.0.1 --directory dist/playground
```

Open `http://127.0.0.1:8878`. This is a development static server, not a household-agent service. Do not expose it to the internet.

## What to try

1. Observe three routine days: there is not yet enough evidence for a candidate.
2. Observe a fourth day: inspect α/β, context strata and source facts.
3. Repeat seven days; then skip a routine in the observed context. Confidence can fall.
4. Add an unknown-cause change. It must not train as human behavior or count as a scored missed action.
5. Simulate an agent action and undo it. This injects a synthetic receipt to exercise β+3 and a human lease; it does not grant execution permission.
6. Enter `不要自动开餐厅灯`. Inspect the typed prohibition. Restore the preceding understanding and see that the observed events remain.
7. Add 35 days without coverage/context. Habits can become dormant while evidence is preserved.

The sandbox is bounded to 90 observed days and thirty memory checkpoints. It uses fixed synthetic dates and a single room. It demonstrates mechanisms; it is not a real household study or a fully general event editor.

## EdgeJev

The browser has a bounded rule parser and explicitly reports that EdgeJev is not loaded. It does not fabricate model answers or timings. A model-equipped Python environment can run:

```bash
python -m moqi.voice_benchmark --model /path/to/jev-int8 --output data/voice-report.json
```

The original runtime and model build instructions are at https://github.com/yzfly/edgejev . We do not redistribute its weights or include an upstream license inside our own license grant.

## Acceptance status

CPython tests cover all synthetic scenarios, feedback, absence of context and rollback. The generated page contains real engine outputs and both main/worker JavaScript were syntax-checked. Full browser rendering and live WebAssembly acceptance remain release gates until verified on a working browser runtime. This development host's Windows socket/CSPRNG errors block the normal local-server and Node/Pyodide acceptance runs; this is not evidence that the browser implementation passed or failed.

`tools/check_wasm.mjs` runs the same commands under the official Pyodide runtime in a normal Node environment, when a local full runtime distribution and its tzdata wheel are available:

```bash
node tools/check_wasm.mjs /path/to/pyodide-full dist/playground/index.html
```

This compatibility check complements browser interaction tests; it does not replace visual, keyboard, small-screen or CDN failure checks.
