"""Version-gated, read-only native field/xref and code evidence capture."""
from __future__ import annotations

import argparse
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import re
import struct

import capstone
import pefile

from tools.probe_stackable_native import CLIENT_SHA


def probe(image, names=(), regions=(), vtables=(), members=(), callees=(), classes=()):
    data = image.read_bytes()
    if hashlib.sha256(data).hexdigest() != CLIENT_SHA:
        raise ValueError('client changed; identify native layouts again')
    pe = pefile.PE(data=data, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    section = next(s for s in pe.sections if s.Name.rstrip(b'\0') == b'.text')
    text = section.get_data()
    text_va = base + section.VirtualAddress
    exception = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    offset = pe.get_offset_from_rva(exception.VirtualAddress)
    entries = sorted(struct.iter_unpack('<III', data[offset:offset+exception.Size]))
    starts = [base+a for a, _, _ in entries]
    pe.parse_data_directories(directories=[3])
    unwind = {base+e.struct.BeginAddress:e for e in pe.DIRECTORY_ENTRY_EXCEPTION}
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True

    def read(va, size):
        at = pe.get_offset_from_rva(va-base)
        return data[at:at+size]

    def region(va, size):
        block = read(va, size)
        entry = unwind.get(starts[bisect_right(starts,va)-1])
        while getattr(entry.unwindinfo,'_chained_entry',None):
            entry = entry.unwindinfo._chained_entry
        return dict(address=hex(va),canonicalFunction=hex(base+entry.struct.BeginAddress),
                    size=size,sha256=hashlib.sha256(block).hexdigest(),
                    instructions=[f'{i.address:x} {i.mnemonic} {i.op_str}' for i in md.disasm(block,va)])

    fields = {}
    all_symbols = {}
    for name in names:
        at = data.find(name.encode('ascii')+b'\0')
        if at < 0:
            fields[name] = dict(missing=True)
            continue
        string_va = base+pe.get_rva_from_offset(at)
        needle = struct.pack('<Q',string_va)
        pointers = [m.start() for m in re.finditer(re.escape(needle),data)]
        symbols = [base+pe.get_rva_from_offset(p)+8 for p in pointers]
        fields[name] = dict(string=hex(string_va),symbols=[hex(p) for p in symbols],references=[])
        all_symbols[string_va] = name
        for va in symbols:
            all_symbols[va] = name
    for m in re.finditer(rb'[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]....',text,re.DOTALL):
        at = text_va+m.start()
        target = at+7+struct.unpack('<i',m.group()[3:])[0]
        if target in all_symbols:
            ix = bisect_right(starts,at)-1
            a,z,_ = entries[ix]
            fields[all_symbols[target]]['references'].append(dict(instruction=hex(at),
                                                                 function=hex(base+a),end=hex(base+z)))
    members_found = {}
    captured = set()
    for member in members:
        refs = []
        needle = struct.pack('<i',member)
        for match in re.finditer(re.escape(needle),text):
            at = text_va+match.start()
            ix = bisect_right(starts,at)-1
            a,z,_ = entries[ix]
            size = z-a
            if size > 25000:
                continue
            instructions = list(md.disasm(read(base+a,size),base+a))
            hits = [i for i in instructions if i.address <= at < i.address+i.size and any(
                operand.type==capstone.CS_OP_MEM and operand.mem.disp==member for operand in i.operands)]
            for hit in hits:
                refs.append(dict(function=hex(base+a),instruction=f'{hit.address:x} {hit.mnemonic} {hit.op_str}'))
            if hits and base+a not in captured:
                regions = [*regions,(base+a,size)]
                captured.add(base+a)
        members_found[hex(member)] = refs
    tables = {}
    for name in classes:
        for match in re.finditer(re.escape(name.encode('ascii')+b'\0'),data):
            at = (match.end()+7)&~7
            values = []
            while at+8<=len(data):
                value = struct.unpack_from('<Q',data,at)[0]
                if not section.VirtualAddress <= value-base < section.VirtualAddress+section.Misc_VirtualSize:
                    break
                values.append(value)
                at += 8
            if len(values)>3:
                start = at-len(values)*8
                tables[hex(base+pe.get_rva_from_offset(start))] = [dict(offset=hex(i*8),function=hex(p)) for i,p in enumerate(values)]
    for va,size in vtables:
        values = struct.unpack('<'+'Q'*(size//8),read(va,size))
        tables[hex(va)] = [dict(offset=hex(i*8),function=hex(p)) for i,p in enumerate(values)]
    call_refs = {hex(va):[] for va in callees}
    for match in re.finditer(rb'\xe8....',text,re.DOTALL):
        at = text_va+match.start()
        target = at+5+struct.unpack('<i',match.group()[1:])[0]
        if target not in callees:
            continue
        ix = bisect_right(starts,at)-1
        a,z,_ = entries[ix]
        if not any(i.address==at and i.mnemonic=='call' for i in md.disasm(read(base+a,z-a),base+a)):
            continue
        call_refs[hex(target)].append(dict(function=hex(base+a),instruction=hex(at),end=hex(base+z)))
        if base+a not in captured:
            regions = [*regions,(base+a,z-a)]
            captured.add(base+a)
    return dict(clientSha256=CLIENT_SHA,fields=fields,vtables=tables,members=members_found,callers=call_refs,
                regions=[region(va,size) for va,size in regions])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--field',action='append',default=[])
    parser.add_argument('--region',action='append',default=[])
    parser.add_argument('--vtable',action='append',default=[])
    parser.add_argument('--member',action='append',default=[])
    parser.add_argument('--callee',action='append',default=[])
    parser.add_argument('--class',dest='classes',action='append',default=[])
    args = parser.parse_args()
    if args.output.exists():
        parser.error('choose a new evidence file')
    pairs = lambda rows: [tuple(int(v,0) for v in row.split(':')) for row in rows]
    result = probe(args.image,args.field,pairs(args.region),pairs(args.vtable),[int(v,0) for v in args.member],[int(v,0) for v in args.callee],args.classes)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(fields=result['fields'],members={k:len(v) for k,v in result['members'].items()},callers=result['callers'],vtableCount=len(result['vtables']),
                          regions=len(result['regions'])),indent=2))


if __name__=='__main__':
    main()
