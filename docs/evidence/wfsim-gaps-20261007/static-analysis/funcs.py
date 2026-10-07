import sys,struct,bisect,os,pickle;sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import pefile,xref
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
md=Cs(CS_ARCH_X86,CS_MODE_64);md.detail=False
B=xref.base
PC=os.path.join(os.path.dirname(os.path.abspath(__file__)),'pdata.pkl')
if os.path.exists(PC): starts,ends=pickle.load(open(PC,'rb'))
else:
    pe=pefile.PE(xref.EXE,fast_load=True)
    sec=[s for s in pe.sections if s.Name.startswith(b'.pdata')][0];d=sec.get_data()
    rows=sorted(struct.unpack_from('<III',d,i)[:2] for i in range(0,len(d)-12,12))
    rows=[r for r in rows if r[0]]
    starts=[r[0] for r in rows];ends=[r[1] for r in rows]
    pickle.dump((starts,ends),open(PC,'wb'))
def func_of(va):
    rva=va-B;i=bisect.bisect_right(starts,rva)-1
    return B+starts[i],B+ends[i]
def disfunc(va,limit=4000):
    s,e=func_of(va);o=s-B-xref.text_va
    return list(md.disasm(xref.text[o:o+(e-s)],s))[:limit]
def rdata_str(rva):
    if xref.rdata_va<=rva<xref.rdata_va+len(xref.rdata):
        o=rva-xref.rdata_va;e=xref.rdata.find(b'\0',o);return xref.rdata[o:min(e,o+80)]
    return None
def floatconst(rva):
    for va,blob in ((xref.rdata_va,xref.rdata),(xref.data_va,xref.data)):
        if va<=rva<va+len(blob)-4:
            return struct.unpack_from('<f',blob,rva-va)[0]
    return None
def annotate(ins):
    import re
    s=f"{hex(ins.address)} {ins.mnemonic} {ins.op_str}"
    m=re.search(r'\[rip ([+-]) (0x[0-9a-f]+)\]',ins.op_str)
    if m:
        tgt=ins.address+ins.size+(int(m.group(2),16)*(1 if m.group(1)=='+' else -1))-B
        st=rdata_str(tgt)
        if st and len(st)>3 and all(32<=c<127 for c in st): s+=f"   ; \"{st.decode()}\""
        elif 'ss' in ins.mnemonic or 'xmm' in ins.op_str:
            f=floatconst(tgt);s+=f"   ; f32={f}"
    return s
if __name__=='__main__':
    va=int(sys.argv[1],16)
    s,e=func_of(va);print('function',hex(s),hex(e),e-s,'bytes')
    for ins in disfunc(va): print(annotate(ins))
