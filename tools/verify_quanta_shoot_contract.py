"""Check original Quanta grenade-shot permission/factor bytes, without gameplay timing.

Requires pefile and Unicorn2.1.4. This checks recovered primitives only; it does
not assert an optimized primary/secondary rotation, recipient coverage or damage
inheritance for every source. No live game process is accessed.
"""
from pathlib import Path
import argparse,hashlib,json,struct,sys
SHA='eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--client-exe',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--dependency-dir',type=Path)
    args=ap.parse_args()
    if args.output.exists():ap.error('preserve evidence: output already exists')
    if args.dependency_dir:sys.path.insert(0,str(args.dependency_dir.resolve()))
    from unicorn import Uc,UC_ARCH_X86,UC_MODE_64
    from unicorn.x86_const import (UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_R8,UC_X86_REG_R9,
                                  UC_X86_REG_RSP,UC_X86_REG_RAX,UC_X86_REG_XMM2)
    import pefile
    raw=args.client_exe.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('client changed; re-audit instruction addresses')
    pe=pefile.PE(data=raw,fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase
    u=Uc(UC_ARCH_X86,UC_MODE_64)
    u.mem_map(base,(pe.OPTIONAL_HEADER.SizeOfImage+4095)&~4095)
    u.mem_write(base,pe.get_memory_mapped_image())
    obj=0x30000000;u.mem_map(obj,0x20000);stop=obj+0x1f000
    def q(address,value):u.mem_write(address,struct.pack('<Q',value))
    rows=[]
    for same in [False,True]:
        for team in [False,True]:
            for player in [False,True]:
                for flags in [0,1,2,4,8,16,32]:
                    u.mem_write(obj,bytes(0x10000));q(obj+0x520,obj+0x2000)
                    q(obj+0x2000,obj+0x3000 if player else 0)
                    u.mem_write(obj+0x688,struct.pack('<I',7))
                    u.mem_write(obj+0x4000,struct.pack('<I',7 if team else 8))
                    u.mem_write(obj+0x5000,bytes([flags]));q(obj+0x10000,stop)
                    for reg,val in [(UC_X86_REG_RCX,obj),(UC_X86_REG_RDX,obj if same else obj+0x6000),
                                    (UC_X86_REG_R8,obj+0x4000),(UC_X86_REG_R9,obj+0x5000),(UC_X86_REG_RSP,obj+0x10000)]:
                        u.reg_write(reg,val)
                    u.emu_start(0x1419e1860,stop,count=100)
                    actual=bool(u.reg_read(UC_X86_REG_RAX)&255)
                    expected=bool((same and flags&1)or(player and flags&8)or(not player and flags&16)
                        or((same or team)and flags&2)or(not(same or team)and flags&4)
                        or(not(same or team)and player and flags&32))
                    assert actual==expected,(same,team,player,flags,actual)
                    rows.append(dict(sameOwner=same,sameTeam=team,player=player,flags=flags,shotBonus=actual))
    factors=[]
    for before in [1.,2.,3.]:
        u.mem_write(obj,bytes(0x10000));u.mem_write(obj+0x18,struct.pack('<f',before));q(obj+0x10000,stop)
        u.reg_write(UC_X86_REG_RCX,obj);u.reg_write(UC_X86_REG_RDX,2)
        u.reg_write(UC_X86_REG_XMM2,int.from_bytes(struct.pack('<f',4.)+bytes(12),'little'))
        u.reg_write(UC_X86_REG_RSP,obj+0x10000);u.emu_start(0x140d12e30,stop,count=100)
        after=struct.unpack('<f',u.mem_read(obj+0x18,4))[0]
        assert after==before*4
        factors.append(dict(before=before,multiplier=4.,after=after))
    regions=[]
    for start,end in [(0x1419e1860,0x1419e18c5),(0x140d12e30,0x140d12ef1)]:
        at=pe.get_offset_from_rva(start-base)
        regions.append(dict(start=hex(start),end=hex(end),sha256=hashlib.sha256(raw[at:at+end-start]).hexdigest()))
    result=dict(clientSha256=SHA,permissionCases=rows,factorCases=factors,regions=regions,
        limits=['Primitive permission and operation2 multiplier only, not a complete damage packet or gameplay clock.',
                'Quanta overrides GrenadeShootPermissions with IS_SAME_FACTION; do not use parent default player-only flag.',
                'Actual source/recipient, aiming time, beam pulse ammo and cube chain need separate routing proof.'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(permissionCases=len(rows),factorCases=len(factors),output=str(args.output))))


if __name__=='__main__':main()
