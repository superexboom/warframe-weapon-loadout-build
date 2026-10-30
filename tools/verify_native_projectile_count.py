"""Execute the pinned game's raw-count emission bypass, without scene simulation."""
from pathlib import Path
import argparse,hashlib,json,struct,sys
SHA='eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--client-exe',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--dependency-dir',type=Path);a=p.parse_args()
    if a.output.exists():p.error('preserve evidence: choose new file')
    if a.dependency_dir:sys.path.insert(0,str(a.dependency_dir.resolve()))
    import pefile
    from unicorn import Uc,UC_ARCH_X86,UC_MODE_64,UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_RCX,UC_X86_REG_RSP,UC_X86_REG_RIP,UC_X86_REG_RAX
    raw=a.client_exe.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('image changed')
    pe=pefile.PE(data=raw,fast_load=True);B=pe.OPTIONAL_HEADER.ImageBase
    u=Uc(UC_ARCH_X86,UC_MODE_64);u.mem_map(B,(pe.OPTIONAL_HEADER.SizeOfImage+4095)&~4095);u.mem_write(B,pe.get_memory_mapped_image())
    O=0x30000000;STOP=O+0xf000;QUERY=STOP+0x10;u.mem_map(O,0x10000);ctx={}
    def q(p,v):u.mem_write(p,struct.pack('<Q',v))
    def hook(_,at,size,data):
        if at==QUERY:ctx['queried']=True;u.emu_stop()
        if at==STOP:ctx['returned']=True;u.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);rows=[]
    for flag in [False,True]:
        for count in [1,2,6,13]:
            u.mem_write(O,bytes(0xf000));ctx={'queried':False,'returned':False};q(O,O+0x1000);q(O+0x1000+0x118,QUERY);q(O+0x28,count)
            u.mem_write(O+0x148,bytes([flag]));sp=O+0xe008;q(sp,STOP);u.reg_write(UC_X86_REG_RSP,sp);u.reg_write(UC_X86_REG_RCX,O)
            u.emu_start(0x140f75d20,STOP+1,count=1000)
            assert ctx['queried']==(not flag) and ctx['returned']==flag
            value=u.reg_read(UC_X86_REG_RAX) if ctx['returned'] else None
            if flag:assert value==count
            rows.append(dict(ignoreFireIterations=flag,rawCount=count,returnedCount=value,weaponMultishotQueried=ctx['queried']))
    off=pe.get_offset_from_rva(0x140f75d20-B)
    result=dict(clientSha256=SHA,function='0x140f75d20',rawCountOffset='0x28',ignoreFlagOffset='0x148',cases=rows,
        codeSha256=hashlib.sha256(raw[off:off+0x474]).hexdigest(),
        limits=['Actual true branch runs whole function; false control stops at the external weapon-modified-count query.',
                'Does not infer chain budgets or child count from this emitted-projectile count. Scene/aim/source damage and downstream spawn are not emulated.'])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(cases=len(rows),output=str(a.output))))


if __name__=='__main__':main()
