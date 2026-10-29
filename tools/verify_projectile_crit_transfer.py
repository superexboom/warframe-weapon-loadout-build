"""Execute pinned projectile crit transfer and the actual upgrade bucket consumer.

This proves a transfer primitive with controlled eligible modifier records. It
cannot by itself establish how many times Zymos prepares its carrier or children.
Requires pefile and Unicorn2.1.4; no game process is accessed.
"""
from pathlib import Path
import argparse, hashlib, json, math, struct, sys
SHA='eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--client-exe',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--dependency-dir',type=Path)
    a=ap.parse_args()
    if a.output.exists():ap.error('preserve evidence: output exists')
    if a.dependency_dir:sys.path.insert(0,str(a.dependency_dir.resolve()))
    import pefile
    from unicorn import Uc,UC_ARCH_X86,UC_MODE_64,UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_R8,UC_X86_REG_R9,UC_X86_REG_RSP,UC_X86_REG_RAX,UC_X86_REG_RIP,UC_X86_REG_XMM0
    raw=a.client_exe.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('client changed; repeat native audit')
    pe=pefile.PE(data=raw,fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase
    u=Uc(UC_ARCH_X86,UC_MODE_64);u.mem_map(base,(pe.OPTIONAL_HEADER.SizeOfImage+4095)&~4095);u.mem_write(base,pe.get_memory_mapped_image())
    O=0x30000000;S=O+0x40000;END=O+0x7f000;u.mem_map(O,0x80000)
    P=O;C=O+0x2000;W=O+0x4000;A=O+0x6000;I=O+0x8000;M=O+0xc000;V=O+0x10000;H=O+0x13000;U=O+0x14000
    def q(p,v):u.mem_write(p,struct.pack('<Q',v))
    def d(p,v):u.mem_write(p,struct.pack('<I',v&0xffffffff))
    def f(p,v):u.mem_write(p,struct.pack('<f',v))
    def rol(x,n):return ((x<<n)|(x>>(32-n)))&0xffffffff
    def initvalue(p,value):
        q(p,0x1420a3d48)
        bits=struct.unpack('<I',struct.pack('<f',value))[0]^((p+12)>>3)^0x8637d1b6
        bits=rol(bits,15);d(p+12,bits);d(p+8,bits^0x2c67b217)
        f(p+0x18,1.);d(p+0x28,0x800000);d(p+0x2c,0x7f7fffff)
    ctx={}
    def ret(value=None):
        if value is not None:u.reg_write(UC_X86_REG_RAX,value)
        sp=u.reg_read(UC_X86_REG_RSP);dest=struct.unpack('<Q',u.mem_read(sp,8))[0]
        u.reg_write(UC_X86_REG_RSP,sp+8);u.reg_write(UC_X86_REG_RIP,dest)
    def hook(uc,at,size,_):
        if at==END:ctx['done']=True;u.emu_stop()
        elif at==END+0x10:ret(I)
        elif at==0x141bf7f80:ret()
        elif at==0x1418c1aa0:ctx['managerCalls']+=1
    u.hook_add(UC_HOOK_CODE,hook)
    def call(addr,rcx,rdx=0,r8=0,r9=0,stack=()):
        sp=S+0x3f000-8;q(sp,END);ctx['done']=False
        for j,v in enumerate(stack):q(sp+0x28+j*8,v)
        for reg,value in [(UC_X86_REG_RSP,sp),(UC_X86_REG_RCX,rcx),(UC_X86_REG_RDX,rdx),(UC_X86_REG_R8,r8),(UC_X86_REG_R9,r9)]:u.reg_write(reg,value)
        u.emu_start(addr,END+1,count=20000)
        if not ctx['done']:raise AssertionError('native instruction budget exhausted')
    def value(p):
        call(0x14123df60,p)
        return struct.unpack('<f',u.reg_read(UC_X86_REG_XMM0).to_bytes(16,'little')[:4])[0]
    cases=[]
    # op0 flat add, op1 add to base, op2 multiply, op3 stacking multiply.
    for member,upgrade,transfer,b in [(0x538,0xf4,0x14140ab20,.05),(0x570,0xf8,0x140848e20,2.3)]:
        for label,mods in [('neutral',[]),('stack',[(3,1.2)]),('flat',[(0,.15)]),('base',[(1,.15)]),('multiply',[(2,2.)]),('mixed',[(3,1.2),(0,.15),(2,1.5)])]:
            for eligible in [False,True]:
                u.mem_write(O,bytes(0x40000));ctx={'managerCalls':0,'done':False}
                q(W+8,0x1428c9770);q(W+0xf8,H);q(H,A);q(A,V);q(V+0x938,END+0x10)
                q(I,0x1422f0c98);q(I+0xc88,H+8);q(H+8,M);q(M,0x142182898)
                q(C+0x708,H+16);q(H+16,W)
                entry=M+0x68+upgrade*16;q(entry,U);d(entry+8,len(mods)*0x58)
                for j,(op,num) in enumerate(mods):
                    record=U+j*0x58;u.mem_write(record+0x11,bytes([op,0x19 if eligible else 0x16]));f(record+0x18,num);d(record+0x38,-1)
                    d(record+0x3c,struct.unpack('<I',u.mem_read(0x14288e5e8,4))[0])
                initvalue(P+member,b);initvalue(C+member,b)
                # Prepare one carrier query through actual weapon->owner->inventory->manager.
                call(0x1401413d0,W,P+member,upgrade,0x19,(0x14288e5e8,0x1e))
                before=value(P+member)
                call(transfer,C,P+member)
                after=value(C+member)
                # The death/explosion path calls this copier after the radial
                # builder. Existing plan CC is ADD; existing plan CD is MULTIPLY.
                if member==0x538:initvalue(C+0x570,2.3)
                else:initvalue(C+0x538,.05)
                plan_cc=O+0x18000;plan_cd=plan_cc+0x40
                initvalue(plan_cc,.1);initvalue(plan_cd,1.5)
                call(0x140ede780,C,plan_cc,plan_cd)
                snapshot=value(plan_cc if member==0x538 else plan_cd)
                snapshot_expected=after+.1*(math.prod(v for op,v in mods if op==2)**2 if eligible else 1.) if member==0x538 else after*1.5
                assert math.isclose(snapshot,snapshot_expected,rel_tol=2e-6,abs_tol=1e-6),(label,hex(member),snapshot,snapshot_expected)
                def expected(n):
                    chosen=mods if eligible else []
                    flat=sum(v for op,v in chosen if op==0)*n;pre=sum(v for op,v in chosen if op==1)*n
                    stack=sum(v for op,v in chosen if op==3)*n;mult=math.prod(v for op,v in chosen if op==2)**n
                    return ((b+pre)*(1+stack)+flat)*mult
                assert math.isclose(before,expected(1),rel_tol=2e-6,abs_tol=1e-6),(label,b,before,expected(1))
                assert math.isclose(after,expected(2),rel_tol=2e-6,abs_tol=1e-6),(label,b,after,expected(2))
                assert ctx['managerCalls']==2
                cases.append(dict(field=hex(member),upgrade=hex(upgrade),base=b,modifiers=mods,eligible=eligible,carrier=before,child=after,radialSnapshot=snapshot,planCriticalChanceBefore=.1,planCriticalMultiplierBefore=1.5,managerCalls=2,
                    buckets=struct.unpack('<8f',u.mem_read(C+member+0x10,32)),flags=u.mem_read(C+member+0x30,1)[0]))
    regions=[]
    for start,end in [(0x14140ab20,0x14140abc6),(0x140848e20,0x140848ebd),(0x1401413d0,0x14014146d),(0x1418c1aa0,0x1418c1d5e),(0x141a1aeb0,0x141a1b03a),(0x140d12e30,0x140d12ef1),(0x14123df60,0x14123dffd),(0x140ede780,0x140ede8a2)]:
        at=pe.get_offset_from_rva(start-base);regions.append(dict(start=hex(start),end=hex(end),sha256=hashlib.sha256(raw[at:at+end-start]).hexdigest()))
    result=dict(clientSha256=SHA,cases=cases,regions=regions,
        sourceRoute='weapon+f8 -> actor+938(supplied inventory) -> actual inventory+408 -> actual UpgradeManager+c0',
        formula='((base+n*ADD_BASE)*(1+n*STACKING_MULTIPLY)+n*ADD)*product(MULTIPLY)^n for n repeated identical eligible queries',
        stubs=['actor+938 returns the controlled inventory','security-cookie verification only'],
        limits=['Eligible upgrade records and source/owner handles are controlled offline inputs; ordinary record filters and bucket/transfer/getter execute original bytes.',
                'No carrier creation sequence, count of all gameplay queries, subsequent victim-side crit transforms, hit events, or gameplay DPS proven.',
                'Repeated query alone does not imply squared STACKING_MULTIPLY: retained buckets add the bonus twice.'])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf8') as fh:json.dump(result,fh,indent=2);fh.write('\n')
    print(json.dumps(dict(cases=len(cases),output=str(a.output))))


if __name__=='__main__':main()
