"""Capture and verify the currently published WFSim execution assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request,urlopen


def fetch(url):
    with urlopen(Request(url,headers={'User-Agent':'WF-Riven-reference-audit/1.0'}),timeout=60) as response:
        return response.read()


def extract_data_pack(runtime: Path, release: dict):
    """Materialize the captured YAML registry; never trust pack paths or hashes."""
    root = (runtime / 'data').resolve()
    count = 0
    for name in release.get('packs') or []:
        match = re.fullmatch(r'pack\.data\.([0-9a-f]{12,64})\.json', name)
        if match is None:
            continue
        raw = (runtime / 'site/pkg' / name).read_bytes()
        if not hashlib.sha256(raw).hexdigest().startswith(match.group(1)):
            raise ValueError('data-pack hash mismatch')
        data = json.loads(raw)
        if data.get('pack') != 'data' or data.get('format') != release.get('data_format', 1):
            raise ValueError('data-pack identity mismatch')
        for relative, contents in data['files'].items():
            target = (root / relative).resolve()
            if (not target.is_relative_to(root) or target == root or '\\' in relative
                    or ':' in relative or not isinstance(contents, str)):
                raise ValueError('invalid data-pack path or content')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding='utf-8')
            count += 1
    if count == 0:
        raise ValueError('captured release has no YAML data pack')
    return count


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
    for name in release.get('packs') or []:
        match=re.fullmatch(r'pack\.(data|site|text)\.([0-9a-f]{12,64})\.json',name)
        if match is None:
            raise ValueError('invalid published data-pack name')
        raw=fetch(base+'pkg/'+name)
        if not hashlib.sha256(raw).hexdigest().startswith(match.group(2)):
            raise ValueError('data-pack hash differs from the published release: '+name)
        payload=json.loads(raw)
        if payload.get('pack')!=match.group(1) or payload.get('format')!=release.get('data_format',1):
            raise ValueError('data-pack identity differs from the published release: '+name)
        paths['site/pkg/'+name]=raw
    wasm=paths[f'site/pkg/wfsim_wasm_bg.{identity}.wasm']
    if not wasm.startswith(b'\0asm') or not hashlib.sha256(wasm).hexdigest().startswith(identity):
        raise ValueError('WASM hash or format differs from the published release')
    after=json.loads(fetch(base+'release.json'))
    if any(after.get(k)!=release.get(k) for k in ('engine','wasm','data','data_format','packs')):
        raise ValueError('published release changed during capture; use a new capture')
    files=[]
    for path,data in paths.items():
        target=args.output/path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
        files.append(dict(path=path,url=base+path.removeprefix('site/'),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
    manifest=dict(release=release,files=files,capturedAt=datetime.now(timezone.utc).isoformat(),
                  contract='Published execution identity stable during capture; data packs verified by their content hashes')
    (args.output/'source.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    extract_data_pack(args.output, release)
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    main()
