"""Resolve current-client private Lua method atoms to read-only native evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import capstone
import pefile

CLIENT_SHA = '45fa6ad0769cc8ca7fa7e0ffdee65c0c0932e11744146781ad18c45b16e4a81c'


def probe(image: Path, scripts: list[Path]):
    body = image.read_bytes()
    if hashlib.sha256(body).hexdigest() != CLIENT_SHA:
        raise ValueError('client identity changed; rebuild symbol-layout proof first')
    pe = pefile.PE(data=body, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    text = next(s for s in pe.sections if s.Name.rstrip(b'\0') == b'.text')
    exception = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    off = pe.get_offset_from_rva(exception.VirtualAddress)
    ends = {a: z for a,z,_ in struct.iter_unpack('<III', body[off:off+exception.Size])}
    methods = {}
    for script in scripts:
        ir = json.loads(script.read_text(encoding='utf-8'))
        for proto in ir['protos']:
            for ins in proto['instructions']:
                if ins['semantic'] != 'NAMECALL':
                    continue
                constant = proto['constants'][ins['aux']]
                if constant.get('kind') != 'private32':
                    continue
                key = constant['raw']
                methods.setdefault(key, dict(callSites=[], bindings=[]))['callSites'].append(
                    dict(script=script.name, proto=proto['index'], pc=ins['pc']))
    for atom, row in methods.items():
        needle = struct.pack('<I', atom)
        offset = 0
        while (offset := body.find(needle, offset)) >= 0:
            try:
                rva = pe.get_rva_from_offset(offset)
                section = pe.get_section_by_rva(rva)
                pointer = struct.unpack_from('<Q', body, offset+8)[0]
                valid = (section.Name.rstrip(b'\0') == b'.rdata'
                         and text.VirtualAddress <= pointer-base < text.VirtualAddress + text.Misc_VirtualSize)
            except (ValueError, pefile.PEFormatError, struct.error):
                valid = False
            if valid:
                code_off = pe.get_offset_from_rva(pointer-base)
                size = min(ends.get(pointer-base, pointer-base+96)-(pointer-base), 2048)
                instructions = list(md.disasm(body[code_off:code_off+size], pointer))
                references = []
                for ins in instructions:
                    if ins.mnemonic != 'lea':
                        continue
                    for operand in ins.operands:
                        if operand.type != capstone.CS_OP_MEM or operand.mem.base != capstone.x86_const.X86_REG_RIP:
                            continue
                        address = ins.address + ins.size + operand.mem.disp
                        try:
                            at = pe.get_offset_from_rva(address-base)
                            value = body[at:at+120].split(b'\0')[0].decode('ascii')
                            if value and all(32 <= ord(c) <= 126 for c in value):
                                references.append(dict(address=hex(address), text=value))
                        except (ValueError, pefile.PEFormatError, UnicodeDecodeError):
                            pass
                row['bindings'].append(dict(table=hex(base+rva), function=hex(pointer),
                    codeSha256=hashlib.sha256(body[code_off:code_off+size]).hexdigest(),
                    references=references,
                    instructions=[f'{i.address:x} {i.mnemonic} {i.op_str}' for i in instructions]))
            offset += 4
    return dict(clientSha256=CLIENT_SHA, scripts=[str(p) for p in scripts], methods=methods)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('scripts', type=Path, nargs='+')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('choose a new evidence file')
    result = probe(args.image, args.scripts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print('atoms', len(result['methods']), 'native bindings', sum(len(r['bindings']) for r in result['methods'].values()))


if __name__ == '__main__':
    main()
