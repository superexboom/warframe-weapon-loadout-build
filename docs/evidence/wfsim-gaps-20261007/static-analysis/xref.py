import pefile, re, pickle, os
import numpy as np
EXE=r'E:\warframe\Warframe\Downloaded\Public\Warframe.x64.exe'
HERE=os.path.dirname(os.path.abspath(__file__))
CACHE=os.path.join(HERE,'image.pkl')
if os.path.exists(CACHE):
    base,text_va,text,rdata_va,rdata,data_va,data=pickle.load(open(CACHE,'rb'))
else:
    pe=pefile.PE(EXE)
    base=pe.OPTIONAL_HEADER.ImageBase
    sec={s.Name.rstrip(b'\0').decode():s for s in pe.sections}
    text_va=sec['.text'].VirtualAddress;text=sec['.text'].get_data()
    rdata_va=sec['.rdata'].VirtualAddress;rdata=sec['.rdata'].get_data()
    data_va=sec['.data'].VirtualAddress;data=sec['.data'].get_data()
    pickle.dump((base,text_va,text,rdata_va,rdata,data_va,data),open(CACHE,'wb'))
_targets=None
def _all_targets():
    """targets[k][i] = rva that a disp32 at text offset p=k+4i would point to (no trailing imm)."""
    global _targets
    if _targets is None:
        _targets=[]
        n=(len(text)-8)//4
        for k in range(4):
            arr=np.frombuffer(text,dtype='<i4',count=n,offset=k).astype(np.int64)
            p=k+4*np.arange(n,dtype=np.int64)
            _targets.append(arr+text_va+p+4)
    return _targets
def str_rvas(s):
    out=[];b=s.encode()+b'\0'
    for m in re.finditer(re.escape(b),rdata):
        if m.start()==0 or rdata[m.start()-1]==0: out.append(rdata_va+m.start())
    return out
def refs(target_rva, imm_sizes=(0,)):
    """text offsets of disp32 fields pointing at target (allowing trailing immediates)."""
    hits=[]
    for imm in imm_sizes:
        for k,t in enumerate(_all_targets()):
            idx=np.nonzero(t+imm==target_rva)[0]
            hits+= [k+4*int(i) for i in idx]
    return sorted(hits)
def calls_to(target_va):
    """E8/E9 rel32 call/jmp sites to target."""
    t=target_va-base-text_va
    out=[]
    for k,arr in enumerate(_all_targets()):
        pass
    import numpy as np
    n=(len(text)-8)//4
    for k in range(4):
        arr=np.frombuffer(text,dtype='<i4',count=n,offset=k).astype(np.int64)
        p=k+4*np.arange(n,dtype=np.int64)
        idx=np.nonzero(arr+p+4==t)[0]
        for i in idx:
            pos=k+4*int(i)
            if text[pos-1] in (0xE8,0xE9): out.append(base+text_va+pos-1)
    return out
def ptrs_to(target_va):
    import struct
    v=struct.pack('<Q',target_va);out=[]
    for va,blob in ((rdata_va,rdata),(data_va,data)):
        i=blob.find(v)
        while i!=-1: out.append(base+va+i);i=blob.find(v,i+1)
    return out
