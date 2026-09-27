import fs from 'node:fs'; import path from 'node:path';
const [repo,input,output]=process.argv.slice(2);
const rel=JSON.parse(fs.readFileSync(path.join(repo,'site/release.json'),'utf8'));
const base=path.join(repo,'site/pkg');
const engine=new Function(fs.readFileSync(path.join(base,'wfsim_wasm.'+rel.wasm+'.js'),'utf8')+';return wasm_bindgen;')();
engine.initSync({module:fs.readFileSync(path.join(base,'wfsim_wasm_bg.'+rel.wasm+'.wasm'))});
const results=JSON.parse(fs.readFileSync(input,'utf8')).map(p=>JSON.parse(engine.api('/api/simulate',JSON.stringify(p))));
fs.writeFileSync(output,JSON.stringify(results,null,2),{flag:'wx'});
