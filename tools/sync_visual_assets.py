"""Import enemy thumbnails and native UI image additions; runtime stays offline."""
from __future__ import annotations
import argparse, hashlib, io, json, re, shutil, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_sources import dataset_root, export_dir
MAX_BYTES = 16 * 1024 * 1024
IMAGE_REF = re.compile(rb'/Lotus/Interface/[A-Za-z0-9_./() -]+?[.](?:png|jpg|jpeg)', re.I)
ICON_LINE = re.compile(r'^Icon=(.*)$', re.M)

def load(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))

def dump(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8', newline=chr(10))
    tmp.replace(p)

def canonical_icon(value):
    if not isinstance(value, str): return None
    if not value.startswith('/Lotus/Interface/') or any(x in value for x in (chr(92), '?', '#', '!', '%', ':')): return None
    if not value.lower().endswith(('.png', '.jpg', '.jpeg')): return None
    if any(x in ('', '.', '..') for x in value[1:].split('/')): return None
    return value

def safe(root, icon):
    if not canonical_icon(icon): raise ValueError('invalid native icon path')
    dest = (root / icon[1:]).resolve()
    dest.relative_to(root.resolve())
    return dest

def validate(raw):
    if not raw or len(raw) > MAX_BYTES: raise ValueError('invalid image bytes')
    with Image.open(io.BytesIO(raw)) as im:
        if im.format not in ('PNG', 'JPEG') or max(im.size) > 8192 or im.width * im.height > 32 * 1024 * 1024: raise ValueError('invalid image dimensions/format')
        im.load()
        return dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), width=im.width, height=im.height, format=im.format, mode=im.mode)

def own_icon(root, path):
    base = root / 'packages' / path.lstrip('/')
    jp = Path(str(base) + '.json'); tp = Path(str(base) + '.txt')
    if jp.is_file():
        obj = load(jp)
        return (obj.get('Icon'), jp) if isinstance(obj, dict) and 'Icon' in obj else (None, None)
    if tp.is_file():
        match = ICON_LINE.search(tp.read_text(encoding='utf-8-sig', errors='replace'))
        if match: return match.group(1).strip().strip(chr(34)), tp
    return None, None

def resolve_icon(root, parents, path):
    current = path; seen = set()
    while current and current not in seen:
        seen.add(current)
        icon, source = own_icon(root, current)
        if source is not None:
            return dict(icon=canonical_icon(icon), iconSourceType=current, inherited=current != path, sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest())
        current = parents.get(current)
    return dict(icon=None)

def image_references(root):
    refs = {p for p in load(root / 'parents.json') if canonical_icon(p)} if (root / 'parents.json').is_file() else set()
    for suffix in ('*.txt', '*.json'):
        for path in (root / 'packages').rglob(suffix):
            for match in IMAGE_REF.finditer(path.read_bytes()):
                icon = match.group().decode('ascii')
                if canonical_icon(icon): refs.add(icon)
    return refs

def fetch(icon, stage, local_roots, base_url):
    dest = safe(stage / 'WRData/icon/OfficialWarframe', icon)
    for source in (dest, *(safe(root, icon) for root in local_roots)):
        if source.is_file():
            try:
                raw = source.read_bytes(); meta = validate(raw)
                if source != dest:
                    dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(raw)
                return icon, dict(**meta, source='existing-local-asset', asset='OfficialWarframe/' + icon[1:])
            except (ValueError, OSError): pass
    url = base_url.rstrip('/') + quote(icon, safe='/'); error = None
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'WF-Riven-AssetMaintenance/1.0'}), timeout=25) as response:
                raw = response.read(MAX_BYTES + 1)
            meta = validate(raw)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + '.tmp'); tmp.write_bytes(raw); tmp.replace(dest)
            return icon, dict(**meta, source='browse.wf-game-resource', sourceUrl=url, asset='OfficialWarframe/' + icon[1:])
        except Exception as exc:
            error = str(exc)
            if isinstance(exc, HTTPError) and exc.code in (400, 403, 404, 410): break
            if attempt < 2: time.sleep(attempt + 1)
    return icon, dict(error=error, asset=None)

def runtime_art(root):
    content = dataset_root(root)
    result = {}
    for family in ('mods', 'stances'):
        base = content / 'frontend/assets' / family / 'art'
        for file in base.rglob('*.png'):
            if file.stem.endswith(('.fg', '.bg')): continue
            icon = canonical_icon('/' + file.relative_to(base).as_posix())
            if icon: result[icon] = file
    for row in load(export_dir(root) / 'arcanes.json')['data']:
        icon = canonical_icon(row.get('icon'))
        if icon:
            file = content / 'frontend/assets/arcanes' / Path(icon).name
            if file.is_file(): result[icon] = file
    return result

def verified_cached_asset(stage, icon, result):
    if not result.get('sha256'): return False
    path = safe(stage / 'WRData/icon/OfficialWarframe', icon)
    try: return hashlib.sha256(path.read_bytes()).hexdigest() == result['sha256']
    except OSError: return False

def inventory(args):
    parents = load(args.raw / 'parents.json')
    enemies = load(export_dir(args.root) / 'enemies.json')['data']
    records = {}
    for enemy in enemies:
        row = resolve_icon(args.raw, parents, enemy['path'])
        if row.get('iconSourceType') == '/Lotus/Types/Enemies/Duviri/Avatars/BaseDuviriAvatar': row['genericPrototype'] = True
        records[enemy['path']] = row
    print('Scanning old/new native UI references...', flush=True)
    old = image_references(args.previous); new = image_references(args.raw)
    icons = {row['icon'] for row in records.values() if row.get('icon')} | (new - old)
    plan = dict(schemaVersion=1, build=args.raw.name, previousBuild=args.previous.name, createdAt=datetime.now(timezone.utc).isoformat(), enemies=records, newIcons=sorted(new-old), icons=sorted(icons), nativeRefCount=len(new), previousRefCount=len(old), parentsSha256=hashlib.sha256((args.raw/'parents.json').read_bytes()).hexdigest())
    dump(args.stage/'inventory.json',plan)
    print(json.dumps({k:len(plan[k]) for k in ('enemies','newIcons','icons')}), flush=True)
    return plan

def sync(args):
    plan = load(args.stage/'inventory.json') if args.resume and (args.stage/'inventory.json').is_file() else inventory(args)
    assets = {}; previous = args.stage/'asset-results.json'
    if args.resume and previous.exists(): assets = load(previous)
    # Also carry exact-path originals already consumed by the current UI.
    runtime = runtime_art(args.root)
    plan['runtimeIcons'] = sorted(runtime)
    plan['icons'] = sorted(set(plan['icons']) | set(runtime))
    dump(args.stage/'inventory.json', plan)
    for icon, source in runtime.items():
        if verified_cached_asset(args.stage, icon, assets.get(icon, {})): continue
        raw = source.read_bytes()
        try: meta = validate(raw)
        except (ValueError, OSError): continue
        target = safe(args.stage / 'WRData/icon/OfficialWarframe', icon)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        assets[icon] = dict(**meta, source='existing-runtime-original', sourcePath=source.relative_to(dataset_root(args.root)).as_posix(), asset='OfficialWarframe/' + icon[1:])
    todo = [i for i in plan['icons'] if not verified_cached_asset(args.stage, i, assets.get(i, {})) and not (args.resume and not args.retry_missing and assets.get(i, {}).get('error'))]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = [pool.submit(fetch, icon, args.stage, args.local_art, args.base_url) for icon in todo]
        for count, future in enumerate(as_completed(tasks), 1):
            icon, result = future.result(); assets[icon] = result
            if count % 40 == 0 or count == len(todo):
                dump(previous,assets); print('Images',count,'/',len(todo),'decoded',sum(bool(x.get('sha256')) for x in assets.values()),flush=True)
    dump(previous,assets)
    dst = dataset_root(args.root) / 'frontend/assets/enemies'
    records = {}
    for path, row in plan['enemies'].items():
        record = dict(row); asset = assets.get(row.get('icon'), {})
        if asset.get('sha256') and not row.get('genericPrototype'):
            source = safe(args.stage/'WRData/icon/OfficialWarframe',row['icon']); target = safe(dst/'art',row['icon'])
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != asset['sha256']: shutil.copyfile(source,target)
            record.update(asset='/assets/enemies/art/'+row['icon'][1:],sha256=asset['sha256'],imageSource=asset['source'],status='inherited' if row.get('inherited') else 'exact')
        else: record.update(asset=None,status='generic-prototype' if row.get('genericPrototype') else 'missing')
        records[path] = record
    manifest = dict(schemaVersion=1,build=plan['build'],previousBuild=plan['previousBuild'],parentsSha256=plan['parentsSha256'], enemies=records)
    dump(dst/'index.json',manifest)
    shared = dict(schemaVersion=1,build=plan['build'],enemies={p:{**r,'asset':assets.get(r.get('icon'),{}).get('asset') if r.get('asset') else None} for p,r in records.items()}, assets=assets, newIcons=plan['newIcons'], runtimeIcons=plan['runtimeIcons'])
    dump(args.stage/'WRData/data/visual-assets/index.json',shared)
    print(json.dumps(dict(enemies=len(records),withImage=sum(bool(r['asset']) for r in records.values()),newIcons=len(plan['newIcons']),images=sum(bool(a.get('sha256')) for a in assets.values()),failed=sum(not bool(a.get('sha256')) for a in assets.values()))),flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw',type=Path,required=True);p.add_argument('--previous',type=Path,required=True)
    p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--stage',type=Path,required=True)
    p.add_argument('--local-art',type=Path,action='append',default=[]);p.add_argument('--workers',type=int,default=4)
    p.add_argument('--retry-missing',action='store_true');p.add_argument('--base-url',default='https://browse.wf');p.add_argument('--resume',action='store_true');p.add_argument('--inventory-only',action='store_true')
    args=p.parse_args()
    if not 1 <= args.workers <= 8:p.error('workers must be 1..8')
    if args.inventory_only:inventory(args)
    else:sync(args)
if __name__=='__main__': main()