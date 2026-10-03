// Optional compatibility check. Pass a directory containing the official
// Pyodide 314.0.7 full runtime and tzdata wheel; no household data is loaded.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const [runtime, htmlPath] = process.argv.slice(2);
if (!runtime || !htmlPath) throw new Error('Usage: node tools/check_wasm.mjs RUNTIME_DIRECTORY PLAYGROUND_HTML');
const root=path.resolve(runtime),html=await fs.readFile(htmlPath,'utf8');
const bundle=JSON.parse(html.match(/<script type="application\/json" id="bundle">([^]*?)<\/script>/)[1]);
const {loadPyodide}=await import(pathToFileURL(path.join(root,'pyodide.mjs')).href);
const py=await loadPyodide({indexURL:root+path.sep});
await py.loadPackage('tzdata');
py.FS.mkdirTree('/home/pyodide/moqi');
for(const [name,body] of Object.entries(bundle.files))py.FS.writeFile('/home/pyodide/'+name,body);
await py.runPythonAsync('import sys\nsys.path.insert(0,"/home/pyodide")\nfrom moqi.playground import Sandbox\nsandbox=Sandbox("/home/pyodide/wasm-check.sqlite3")');
const sandbox=py.globals.get('sandbox');
function call(command){return JSON.parse(sandbox.dispatch_json(JSON.stringify(command)));}
assert.equal(call({action:'inspect'}).habits.length,0);
let state=call({action:'week',mode:'routine'});
assert.equal(state.observed_days,7);assert.ok(state.habits.length>0);
state=call({action:'day',mode:'unknown'});assert.equal(state.forecasts[0].outcome,'unscored');
state=call({action:'day',mode:'skip'});assert.ok(state.habits.some(h=>h.failures>0));
state=call({action:'undo'});assert.ok(state.leases.length>0);
state=call({action:'correct',text:'不要自动开餐厅灯'});assert.equal(state.constraints.length,1);
const events=state.event_count;state=call({action:'rollback'});assert.equal(state.constraints.length,0);assert.equal(state.event_count,events);
state=call({action:'quiet'});assert.ok(state.habits.every(h=>h.status==='seasonal_dormant'));
sandbox.close();sandbox.destroy();
console.log(JSON.stringify({status:'passed',runtime:'Pyodide '+bundle.pyodide_version,
    commands:8,backend:'actual Python + SQLite in WebAssembly',physical_execution:false}));
