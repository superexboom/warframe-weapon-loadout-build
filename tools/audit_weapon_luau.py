"""Decode weapon bytecode with the current client map, preserving private atoms."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from extract_ability_luau_ir import RAW_OPS, parse_chunk

# Luau comparison jumps carry an AUX register. The older query-only map did
# not encounter JUMPIFLT in queries and recorded its width as one.
BASE_OPS = {**RAW_OPS, 0x21: ('JUMPIFLT', 2),
            0x0A: ('FORNLOOP', 1), 0x47: ('FORNPREP', 1),
            0x3F: ('SETLIST', 2), 0x2A: ('SETTABLE', 1), 0x05: ('JUMPBACK', 1)}


def instructions(proto: dict, mapping: dict) -> list[dict]:
    result = []
    words = [int(word, 16) for word in proto['codeWords']]
    pc = 0
    while pc < len(words):
        word = words[pc]
        op, a, b, c = word & 255, word >> 8 & 255, word >> 16 & 255, word >> 24
        semantic, width = mapping.get(op, (f'raw_0x{op:02x}', 1))
        d = word >> 16
        result.append(dict(pc=pc, op=op, semantic=semantic, a=a, b=b, c=c,
                           sd=d-65536 if d >= 32768 else d,
                           aux=words[pc+1] if width==2 and pc+1<len(words) else None, width=width))
        pc += width
    return result


def transfer_map(pairs: list[tuple[Path, Path]]) -> dict:
    """Only unchanged full register/operand streams establish a permutation."""
    mapping = {}
    evidence = []
    for old_path, new_path in pairs:
        old_body, new_body = old_path.read_bytes(), new_path.read_bytes()
        old, new = parse_chunk(old_body), parse_chunk(new_body)
        matched = []
        for before, after in zip(old['protos'], new['protos']):
            if any(before[k] != after[k] for k in ('lineDefined', 'params', 'upvalues')):
                continue
            a, b = before['codeWords'], after['codeWords']
            if len(a) != len(b):
                continue
            old_instructions = instructions(before, BASE_OPS)
            if any(i['op'] not in BASE_OPS for i in old_instructions):
                continue
            masks = {i['pc']: (0x00FFFF00 if i['semantic'] in
                     {'GETGLOBAL', 'SETGLOBAL', 'GETTABLEKS', 'SETTABLEKS', 'NAMECALL'}
                     else 0xFFFFFF00) for i in old_instructions}
            # C is a mutable lookup-cache hint on these operations. AUX words
            # and every other register/operand must agree exactly.
            if any((int(u,16) & masks.get(pc, 0xFFFFFFFF)) !=
                   (int(v,16) & masks.get(pc, 0xFFFFFFFF))
                   for pc,(u,v) in enumerate(zip(a,b))):
                continue
            matched.append(before['index'])
            for ins in old_instructions:
                if ins['op'] not in BASE_OPS:
                    continue
                opcode = int(b[ins['pc']], 16) & 255
                entry = BASE_OPS[ins['op']]
                if opcode in mapping and mapping[opcode] != entry:
                    raise ValueError(f'conflicting opcode 0x{opcode:02x}')
                mapping[opcode] = entry
        evidence.append({
            'old': str(old_path), 'new': str(new_path),
            'oldSha256': hashlib.sha256(old_body).hexdigest(),
            'newSha256': hashlib.sha256(new_body).hexdigest(),
            'matchedProtos': matched,
        })
    if len(set(mapping.values())) != len(mapping):
        aliases = {name: [hex(k) for k,v in mapping.items() if v == name]
                   for name in set(mapping.values()) if list(mapping.values()).count(name) > 1}
        raise ValueError(f'mapping is not a permutation: {aliases}')
    return {'mapping': {str(k): v for k, v in sorted(mapping.items())}, 'sources': evidence}


def decode(path: Path, mapping: dict | None = None) -> dict:
    body = path.read_bytes()
    chunk = parse_chunk(body)
    protos = []
    for proto in chunk['protos']:
        decoded = instructions(proto, mapping or BASE_OPS)
        starts = {i['pc'] for i in decoded} | {len(proto['codeWords'])}
        unknown = []
        bad_jumps = []
        for ins in decoded:
            if ins['op'] not in (mapping or BASE_OPS):
                unknown.append(ins['pc'])
            if ins['semantic'].startswith('JUMP'):
                dest = ins['pc'] + 1 + ins['sd']
                ins['target'] = dest
                if dest not in starts:
                    bad_jumps.append(ins['pc'])
        protos.append({
            'index': proto['index'], 'lineDefined': proto['lineDefined'],
            'params': proto['params'], 'upvalues': proto['upvalues'],
            'children': proto['children'], 'constants': proto['constants'],
            'instructions': decoded, 'unknownPcs': unknown,
            'invalidJumpPcs': bad_jumps,
        })
    return {
        'path': str(path), 'sha256': hashlib.sha256(body).hexdigest(),
        'bytes': len(body), 'version': chunk['version'],
        'mainProto': chunk['mainProto'],
        'decoderSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'opcodeMapSha256': hashlib.sha256(
            json.dumps(mapping or BASE_OPS, sort_keys=True).encode()).hexdigest(),
        'protos': protos,
    }


def render(result: dict) -> str:
    rows = [f"sha256={result['sha256']}"]
    for proto in result['protos']:
        rows.append(f"\nP{proto['index']} line={proto['lineDefined']} params={proto['params']} upvalues={proto['upvalues']}")
        for index, const in enumerate(proto['constants']):
            rows.append(f"  K{index}: {json.dumps(const, ensure_ascii=False)}")
        for ins in proto['instructions']:
            note = f" -> {ins['target']}" if 'target' in ins else ''
            if ins['aux'] is not None:
                note += f" aux=0x{ins['aux']:08x}"
            rows.append(f"  {ins['pc']:4} {ins['semantic']:18} A={ins['a']} B={ins['b']} C={ins['c']} D={ins['sd']}{note}")
        rows.append(f"  unknown={proto['unknownPcs']} invalidJumps={proto['invalidJumpPcs']}")
    return '\n'.join(rows) + '\n'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('bodies', type=Path, nargs='+')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--map-pair', type=Path, nargs=2, action='append', default=[])
    ap.add_argument('--map-root', type=Path, nargs=2)
    ap.add_argument('--opcode-map', type=Path)
    args = ap.parse_args()
    if args.output.exists():
        ap.error('choose a new evidence directory')
    args.output.mkdir(parents=True)
    mapping = None
    if args.opcode_map:
        source = json.loads(args.opcode_map.read_text(encoding='utf-8'))
        mapping = {int(k): tuple(v) for k,v in source['mapping'].items()}
    if args.map_root:
        old_root, new_root = args.map_root
        for new_path in sorted(new_root.rglob('*.lua_B')):
            old_path = old_root / new_path.relative_to(new_root)
            if not old_path.is_file():
                continue
            old, new = parse_chunk(old_path.read_bytes()), parse_chunk(new_path.read_bytes())
            old_first = old['protos'][old['mainProto']]['codeWords'][0]
            new_first = new['protos'][new['mainProto']]['codeWords'][0]
            if (int(old_first,16) & 255) != (int(new_first,16) & 255):
                args.map_pair.append((old_path,new_path))
    if args.map_pair:
        transferred = transfer_map(args.map_pair)
        (args.output / 'opcode-map.json').write_text(json.dumps(transferred, indent=2) + '\n', encoding='utf-8')
        mapping = {int(k): tuple(v) for k,v in transferred['mapping'].items()}
    for path in args.bodies:
        result = decode(path, mapping)
        name = path.name.removesuffix('.lua_B')
        (args.output / (name + '.json')).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (args.output / (name + '.txt')).write_text(render(result), encoding='utf-8')
        print(name, result['sha256'], 'unknown=', sum(len(p['unknownPcs']) for p in result['protos']),
              'invalidJumps=', sum(len(p['invalidJumpPcs']) for p in result['protos']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
