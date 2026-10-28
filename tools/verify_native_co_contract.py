"""Execute the pinned game's original GunCO consumer with controlled dependencies.

Requires pefile and Unicorn 2.1.4 (pip install unicorn==2.1.4 pefile). Supply
--dependency-dir only when using an existing isolated research installation.
No game process is opened or changed; the executable is read into an emulator.
This verifies the native core contract, not any weapon's actual caller context.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dependency-dir', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('preserve previous evidence; choose a new output file')
    if args.dependency_dir:
        sys.path.insert(0, str(args.dependency_dir.resolve()))
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
    from unicorn.x86_const import (
        UC_X86_REG_RSP, UC_X86_REG_RIP, UC_X86_REG_EDX, UC_X86_REG_R8D,
        UC_X86_REG_RAX, UC_X86_REG_RBX, UC_X86_REG_RBP, UC_X86_REG_RSI,
        UC_X86_REG_RDI, UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8,
        UC_X86_REG_R9, UC_X86_REG_R10, UC_X86_REG_R11, UC_X86_REG_R12,
        UC_X86_REG_R13, UC_X86_REG_R14, UC_X86_REG_R15,
        UC_X86_REG_XMM0, UC_X86_REG_XMM1, UC_X86_REG_XMM3)
    import pefile
    EXE = args.client_exe
    raw=EXE.read_bytes();SHA='eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d';
    if hashlib.sha256(raw).hexdigest() != SHA:
     raise ValueError('client changed; re-audit native offsets before execution')
    pe=pefile.PE(data=raw,fast_load=True);BASE=pe.OPTIONAL_HEADER.ImageBase
    u=Uc(UC_ARCH_X86,UC_MODE_64);u.mem_map(BASE,(pe.OPTIONAL_HEADER.SizeOfImage+4095)&~4095);u.mem_write(BASE,pe.get_memory_mapped_image())
    O=0x20000000;STACK=0x30000000;STOP=0x40000000
    u.mem_map(O,0x20000);u.mem_map(STACK,0x20000);u.mem_map(STOP,4096)
    CTX=O;WEAPON=O+0x1000;EVENT=O+0x2000;VICTIM=O+0x3000;STATUS=O+0x4000;VT=O+0x5000;OWNER=O+0x6000;HANDLE=O+0x7000
    GET_STATUS,IS_STATUS,POST_CONSUMER=STOP+0x10,STOP+0x20,STOP+0x30
    STUBS={'buildVictimConditionalList':0x1407de4b0,'hasUpgrade':0x140aba1f0,'alternateMode':0x140759f40,'readCurrentDamage':0x1402ec0f0,'queryUpgrade':0x140187990,'checkCookie':0x141bf7f80}
    ctx={}
    def q(a,v=None):
     if v is None:return struct.unpack('<Q',u.mem_read(a,8))[0]
     u.mem_write(a,struct.pack('<Q',v))
    def f(a,v=None):
     if v is None:return struct.unpack('<f',u.mem_read(a,4))[0]
     u.mem_write(a,struct.pack('<f',v))
    def xmm(reg,v):u.reg_write(reg,int.from_bytes(struct.pack('<f',v)+bytes(12),'little'))
    def xf(reg):return struct.unpack('<f',u.reg_read(reg).to_bytes(16,'little')[:4])[0]
    def ret():
     sp=u.reg_read(UC_X86_REG_RSP);u.reg_write(UC_X86_REG_RIP,q(sp));u.reg_write(UC_X86_REG_RSP,sp+8)
    def hook(uc,a,size,_):
     if a==STOP:ctx['completed']=True;u.emu_stop();return
     if a==STUBS['buildVictimConditionalList']:
      ptr=u.reg_read(UC_X86_REG_R8);q(ptr,0);q(ptr+8,0);ret();return
     if a==STUBS['hasUpgrade']:
      upgrade=u.reg_read(UC_X86_REG_EDX);ctx['hasQueries'].append(upgrade)
      u.reg_write(UC_X86_REG_RAX,int(ctx['upgradePresent'] and upgrade==259));ret();return
     if a==STUBS['alternateMode']:u.reg_write(UC_X86_REG_RAX,0);ret();return
     if a==STUBS['readCurrentDamage']:xmm(UC_X86_REG_XMM0,ctx['currentDamage']);ret();return
     if a==STUBS['queryUpgrade']:
      upgrade=u.reg_read(UC_X86_REG_R8D);sp=u.reg_read(UC_X86_REG_RSP);ptype=u.mem_read(sp+0x38,1)[0];base=xf(UC_X86_REG_XMM1)
      ctx['valueQueries'].append(dict(upgrade=upgrade,procType=ptype,base=base))
      xmm(UC_X86_REG_XMM0,base*(1+ctx['perStatus']));ret();return
     if a==GET_STATUS:u.reg_write(UC_X86_REG_RAX,STATUS);ret();return
     if a==IS_STATUS:
      ptype=u.reg_read(UC_X86_REG_EDX);u.reg_write(UC_X86_REG_RAX,int(ptype in ctx['statuses']));ret();return
     if a in (POST_CONSUMER,STUBS['checkCookie']):ret();return
    u.hook_add(UC_HOOK_CODE,hook)

    def rol32(n,k):return ((n<<k)|(n>>(32-k)))&0xffffffff

    def run(hit,proc,statuses,per_status,base,current,present=True,alive=True):
     nonlocal ctx
     ctx=dict(completed=False,upgradePresent=present,currentDamage=current,perStatus=per_status,statuses=statuses,hasQueries=[],valueQueries=[])
     u.mem_write(O,bytes(0x10000));u.mem_write(STACK,bytes(0x20000))
     q(CTX+0xc8,WEAPON);q(WEAPON,VT);q(WEAPON+0xf8,HANDLE);q(HANDLE,OWNER if alive else 0)
     q(VICTIM,VT);q(STATUS,VT);q(VT+0x908,GET_STATUS);q(VT+0x4c8,IS_STATUS);q(VT+0xac0,POST_CONSUMER)
     u.mem_write(EVENT+0x1bf,bytes([hit]));u.mem_write(EVENT+0x268,bytes([proc]));f(EVENT+0x6c,current)
     sp=STACK+0x18000-8;q(sp,STOP)
     for reg in [UC_X86_REG_RAX,UC_X86_REG_RBX,UC_X86_REG_RBP,UC_X86_REG_RSI,UC_X86_REG_RDI,UC_X86_REG_R8,UC_X86_REG_R9,UC_X86_REG_R10,UC_X86_REG_R11,UC_X86_REG_R12,UC_X86_REG_R13,UC_X86_REG_R14,UC_X86_REG_R15]:u.reg_write(reg,0)
     u.reg_write(UC_X86_REG_RSP,sp);u.reg_write(UC_X86_REG_RCX,CTX);u.reg_write(UC_X86_REG_RDX,EVENT);u.reg_write(UC_X86_REG_R8,VICTIM);xmm(UC_X86_REG_XMM3,base)
     u.emu_start(0x14113e250,STOP+1,count=10000)
     assert ctx['completed'],ctx
     if ctx['hasQueries']:
      bits=struct.unpack('<I',u.mem_read(EVENT+0x6c,4))[0];bits=rol32(bits,17)^((EVENT+0x6c)>>3)^0x8637d1b6;value=struct.unpack('<f',struct.pack('<I',bits&0xffffffff))[0]
     else:value=current
     expected=current+len(statuses)*base*per_status if hit!=7 and proc==30 and alive and present else current
     assert abs(value-expected)<1e-4,(value,expected,ctx)
     return dict(hitType=hit,procContext=proc,statuses=statuses,perStatus=per_status,base=base,current=current,upgradePresent=present,alive=alive,result=value,expected=expected,hasQueries=ctx['hasQueries'],valueQueries=ctx['valueQueries'])
    rows=[]
    for hit in [1,2,3,4,5,6,7]:
     for proc in [30,5]:
      for present in [False,True]:
       rows.append(run(hit,proc,[1,5],.8,100.,200.,present))
    for alive in [False,True]:rows.append(run(4,30,[1,5],.8,100.,200.,True,alive))
    for base in [100.,200.]:
     for hit in [1,2,4]:rows.append(run(hit,30,[1,5],.8,base,200.,True))
    start=pe.get_offset_from_rva(0x113e250);code=raw[start:start+0x7b0]
    result=dict(clientSha256=SHA,region=dict(start='0x14113e250',bytes=0x7b0,sha256=hashlib.sha256(code).hexdigest()),cases=len(rows),stubs=STUBS,rows=rows,limits=['External upgrade lookup, current damage read, victim statuses and logging are dependency stubs. Original CO consumer code is unchanged.','Does not establish which real weapon path supplies upgradePresent or the base/current ratio.','No blanket rule can be inferred from radial type or DealDamageThroughImpactBehavior alone.'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(cases=len(rows), clientSha256=SHA, output=str(args.output))))


if __name__ == '__main__':
    main()
