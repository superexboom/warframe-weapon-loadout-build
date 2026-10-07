import sys;sys.path.insert(0,'.')
import xref
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
md=Cs(CS_ARCH_X86,CS_MODE_64)
B=xref.base
def dis(va,count=80,before=0):
    o=va-B-xref.text_va-before
    out=[]
    for ins in md.disasm(xref.text[o:o+count*15],va-before):
        out.append(ins)
        if len(out)>=count:break
    return out
if __name__=='__main__':
    va=int(sys.argv[1],16);n=int(sys.argv[2]) if len(sys.argv)>2 else 80;b=int(sys.argv[3]) if len(sys.argv)>3 else 0
    for i in dis(va,n,b): print(hex(i.address),i.mnemonic,i.op_str)
