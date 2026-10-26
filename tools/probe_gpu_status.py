"""Measure a real proc-kernel recurrence; not an end-to-end combat benchmark."""
import argparse,ctypes as c,hashlib,json,random,statistics,subprocess,sys,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--simfleet-root',type=Path,required=True,help='Read-only simfleet checkout providing experiments/hardware/cuda_driver.py')
parser.add_argument('--nvrtc-dir',type=Path,required=True,help='Directory containing NVRTC 12.x DLLs and nvrtc-builtins64_129.dll')
parser.add_argument('--output',type=Path,required=True,help='New directory for isolated native prototype and results')
args=parser.parse_args()
SIMFLEET=args.simfleet_root.resolve();HERE=args.output.resolve()
if HERE.exists():parser.error('choose a new output directory')
HERE.mkdir(parents=True)
shutil.copy2(Path(__file__).with_name('gpu_status_probe.cu'),HERE/'gpu-status.cu')
sys.path.insert(0,str(SIMFLEET/'experiments/hardware'))
from cuda_driver import Cuda
rust=(f'#[path={json.dumps((ROOT/"native/wfcore/src/pymath.rs").as_posix())}] mod pymath;\n'
      f'#[path={json.dumps((ROOT/"native/wfcore/src/proc.rs").as_posix())}] mod proc;\n'+r'''
#[no_mangle]
pub unsafe extern "C" fn status_batch(input:*const f64, output:*mut f64, count:usize, steps:usize) {
    let input=std::slice::from_raw_parts(input,count*2);
    let output=std::slice::from_raw_parts_mut(output,count*11);
    for lane in 0..count {
        let mut dist=vec![1.0];dist.extend([0.0;10]);
        if let Some(kernel)=proc::arrival_kernel(input[lane*2],input[lane*2+1],10) {
            for _ in 0..steps {dist=proc::fold(&dist,&kernel,10);}
        }
        output[lane*11..lane*11+11].copy_from_slice(&dist);
    }
}
''')
(HERE/'status-cpu.rs').write_text(rust,encoding='utf-8')
p=subprocess.run(['rustc','--crate-type','cdylib','-O','--edition=2021','-A','dead_code',str(HERE/'status-cpu.rs'),'-o',str(HERE/'status-cpu.dll')],capture_output=True,text=True)
if p.returncode:raise RuntimeError(p.stderr)
cpu=c.CDLL(str(HERE/'status-cpu.dll'));cpu.status_batch.argtypes=[c.POINTER(c.c_double),c.POINTER(c.c_double),c.c_size_t,c.c_size_t]
nvrtc=args.nvrtc_dir.resolve()
rows=[]
with Cuda(nvrtc) as gpu:
    started=time.perf_counter();ptx=gpu.compile(HERE/'gpu-status.cu');compile_seconds=time.perf_counter()-started
    for count in [1,8,32,128,512,2048,8192]:
        rng=random.Random(19531);inputs=(c.c_double*(count*2))()
        for i in range(count):
            absence=rng.uniform(.02,.99);inputs[2*i]=absence;inputs[2*i+1]=(1-absence)*rng.uniform(.2,3.0)
        expected=(c.c_double*(count*11))();actual=(c.c_double*(count*11))()
        din=gpu.allocate(c.sizeof(inputs));dout=gpu.allocate(c.sizeof(actual));times=[];host=[]
        for repeat in range(6):
            started=time.perf_counter();cpu.status_batch(inputs,expected,count,180);cpu_time=time.perf_counter()-started
            started=time.perf_counter();gpu.upload(din,inputs);gpu.launch('status_batch',count,[din,dout,c.c_int(count),c.c_int(180)]);gpu.download(actual,dout);gpu_time=time.perf_counter()-started
            assert bytes(actual)==bytes(expected),(count,max(abs(a-b) for a,b in zip(actual,expected)))
            if repeat:host.append(cpu_time);times.append(gpu_time)
        row=dict(candidates=count,steps=180,cpu_seconds=statistics.median(host),gpu_roundtrip_seconds=statistics.median(times),exact=True)
        rows.append(row);print(json.dumps(row),flush=True)
    out=dict(device=gpu.name,architecture=gpu.arch,options=gpu.options,compile_seconds=compile_seconds,
             source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'native/wfcore/src/proc.rs',ROOT/'native/wfcore/src/pymath.rs']},
             cpu_sha256=hashlib.sha256((HERE/'status-cpu.dll').read_bytes()).hexdigest(),ptx_sha256=hashlib.sha256(ptx).hexdigest(),
             scope='Capped proc distribution repeated arrivals; no expiry, target damage, resolver, complete candidate scoring or production integration',rows=rows)
(HERE/'gpu-status-results.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
