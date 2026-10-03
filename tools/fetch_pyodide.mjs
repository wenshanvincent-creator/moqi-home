// Fetch a pinned, isolated official runtime for the compatibility check.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
const target=path.resolve(process.argv[2]||'.cache/pyodide-314.0.7');
const base='https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
async function bytes(name){const r=await fetch(base+name,{signal:AbortSignal.timeout(60000)});if(!r.ok)throw Error(name+': '+r.status);return Buffer.from(await r.arrayBuffer());}
const lockBytes=await bytes('pyodide-lock.json'),lock=JSON.parse(lockBytes),timezone=lock.packages.tzdata;
if(!/^[a-zA-Z0-9_.-]+$/.test(timezone.file_name))throw Error('Unsafe runtime package filename');
await fs.mkdir(target,{recursive:true});
const assets=['pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','python_stdlib.zip',timezone.file_name];
for(const name of assets){const body=await bytes(name);if(name===timezone.file_name&&createHash('sha256').update(body).digest('hex')!==timezone.sha256)throw Error('tzdata integrity mismatch');await fs.writeFile(path.join(target,name),body);}
await fs.writeFile(path.join(target,'pyodide-lock.json'),lockBytes);
console.log('Prepared Pyodide 314.0.7 at '+target);
