"""Capture and verify the currently published WFSim execution assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request,urlopen


def fetch(url):
    with urlopen(Request(url,headers={'User-Agent':'WF-Riven-reference-audit/1.0'}),timeout=60) as response:
        return response.read()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('choose a new output directory')
    base='https://wfsim.app/'
    release_data=fetch(base+'release.json')
    release=json.loads(release_data)
    identity=release['wasm']
    if not identity or any(ch not in '0123456789abcdef' for ch in identity):
        raise ValueError('invalid published WASM identity')
    paths={'site/release.json':release_data}
    for name in [f'wfsim_wasm.{identity}.js',f'wfsim_wasm_bg.{identity}.wasm']:
        paths['site/pkg/'+name]=fetch(base+'pkg/'+name)
    wasm=paths[f'site/pkg/wfsim_wasm_bg.{identity}.wasm']
    if not wasm.startswith(b'\0asm') or not hashlib.sha256(wasm).hexdigest().startswith(identity):
        raise ValueError('WASM hash or format differs from the published release')
    if json.loads(fetch(base+'release.json'))!=release:
        raise ValueError('published release changed during capture; use a new capture')
    files=[]
    for path,data in paths.items():
        target=args.output/path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
        files.append(dict(path=path,url=base+path.removeprefix('site/'),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
    manifest=dict(release=release,files=files,contract='Published runtime captured atomically; YAML source is recorded separately')
    (args.output/'source.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    main()
