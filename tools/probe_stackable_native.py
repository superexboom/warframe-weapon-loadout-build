"""Record version-bound StackableProjectile serializer/default evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import capstone
import pefile


CLIENT_SHA = '45fa6ad0769cc8ca7fa7e0ffdee65c0c0932e11744146781ad18c45b16e4a81c'


def probe(image: Path) -> dict:
    data = image.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != CLIENT_SHA:
        raise ValueError('client changed; re-identify serializer and constructor first')
    pe = pefile.PE(data=data, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True

    def read(va, count):
        off = pe.get_offset_from_rva(va-base)
        return data[off:off+count]

    def dis(va, count):
        return list(md.disasm(read(va,count), va))

    fields = {}
    last_member = None
    schema = dis(0x1415fc260, 0x900)
    for ins in schema:
        if ins.mnemonic != 'lea' or len(ins.operands) != 2:
            continue
        dest, source = ins.operands
        if source.type != capstone.CS_OP_MEM:
            continue
        mem = source.mem
        if mem.base == capstone.x86_const.X86_REG_RDI:
            last_member = mem.disp
        elif mem.base == capstone.x86_const.X86_REG_RIP:
            va = ins.address + ins.size + mem.disp
            if 0x14286da00 <= va <= 0x14286dc30:
                name_va = struct.unpack('<Q', read(va-8,8))[0]
                try:
                    name = read(name_va,100).split(b'\0')[0].decode('ascii')
                except (ValueError, UnicodeDecodeError):
                    continue
                if name.startswith('m'):
                    fields[name] = {'offset': last_member, 'schemaInstruction': hex(ins.address)}
    ctor = dis(0x141be8a70, 0x143)
    if not any(i.mnemonic == 'lea' and 'rip + 0x7df4bf' in i.op_str for i in ctor):
        raise ValueError('StackableProjectile vtable identity changed')
    curve = dis(0x140212ed0, 0x577)
    defaults = {'maxProjectileStack':10, 'stackHitProxyDamage':False,
                'resetMaxLifeOnStack':False, 'checkCollisionsWithinProjGroup':True,
                'stackedMaxLife':-1., 'stackingDamage':[0.,0.], 'stackingDamageRange':[1.,5.]}
    return {
        'image': str(image), 'sha256': digest,
        'serializer': hex(0x1415fc260), 'constructor': hex(0x141be8a70),
        'vtable': hex(0x1423c7f48), 'defaults': defaults,
        'fields': fields,
        'serializerDisassembly': [f'{i.address:x} {i.mnemonic} {i.op_str}' for i in schema],
        'constructorDisassembly': [f'{i.address:x} {i.mnemonic} {i.op_str}' for i in ctor],
        'stackAttackBuilder':hex(0x140212ed0),
        'stackAttackDisassembly': [f'{i.address:x} {i.mnemonic} {i.op_str}' for i in curve],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        ap.error('choose a new evidence file')
    result = probe(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['fields'], indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
