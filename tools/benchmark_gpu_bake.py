"""Bounded, exact GPU microbenchmarks with 1/8/16 CPU lanes and transfer costs.

No simulation/cache result is produced. Both kernels must match production
Rust proc arithmetic bit for bit; timings never claim complete bake speedup.
"""
from __future__ import annotations
import argparse,ctypes as c,hashlib,json,random,statistics,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

RUST = r'''
#[no_mangle]
pub unsafe extern "C" fn bench(input:*const f64,output:*mut f64,count:usize,steps:usize,offset:usize,kind:usize){
 let input=std::slice::from_raw_parts(input,count*2);
 let width=if kind==0 {11} else {12};let output=std::slice::from_raw_parts_mut(output,count*width);
 for lane in 0..count {
  if kind==0 {
   let mut dist=vec![1.0];dist.extend([0.0;10]);
   if let Some(kernel)=proc::arrival_kernel(input[lane*2],input[lane*2+1],10){
    for _ in 0..steps {dist=proc::fold(&dist,&kernel,10);}
   }
   output[lane*width..lane*width+11].copy_from_slice(&dist);
  } else {
   let mut pool=proc::CappedPool::new(10.);let mut checksum=0.;
   let lifetime=(10+(lane+offset)%30) as f64 * 0.1;
   for event in 0..steps {
    let t=event as f64 * 0.1;
    if event>0 && event%(37+(lane+offset)%23)==0 {pool.reset();}
    pool.expire(t);
    let absence=input[lane*2]*(1+event%7) as f64 /8.;
    let expected=input[lane*2+1]*(1.+(event%5) as f64 *0.25);
    pool.add(t+lifetime,absence,expected);
    for (k,v) in pool.distribution().iter().enumerate(){checksum+=k as f64 * v;}
   }
   output[lane*width..lane*width+11].copy_from_slice(pool.distribution());
   output[lane*width+11]=checksum;
  }
 }
}
'''


def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--simfleet-root',type=Path,required=True);ap.add_argument('--nvrtc-dir',type=Path,required=True)
 ap.add_argument('--output',type=Path,required=True);ap.add_argument('--repeats',type=int,default=3)
 args=ap.parse_args();out=args.output.resolve()
 if out.exists():ap.error('new directory required')
 out.mkdir(parents=True)
 sys.path.insert(0,str(args.simfleet_root/'experiments/hardware'));from cuda_driver import Cuda
 source=out/'cpu.rs';source.write_text(f'#[path={json.dumps((ROOT/"native/wfcore/src/pymath.rs").as_posix())}] mod pymath;\n'+f'#[path={json.dumps((ROOT/"native/wfcore/src/proc.rs").as_posix())}] mod proc;\n'+RUST,encoding='utf-8')
 compile_result=subprocess.run(['rustc','--crate-type','cdylib','-O','--edition=2021','-A','dead_code',str(source),'-o',str(out/'cpu.dll')],capture_output=True,text=True)
 if compile_result.returncode:raise RuntimeError(compile_result.stderr)
 cpu=c.CDLL(str(out/'cpu.dll'));cpu.bench.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.c_size_t,c.c_size_t,c.c_size_t]
 def load():
  return subprocess.check_output(['nvidia-smi','--query-gpu=utilization.gpu,utilization.memory,memory.used,power.draw','--format=csv,noheader'],text=True).strip()
 rows=[];before=load()
 with Cuda(args.nvrtc_dir.resolve()) as gpu,ThreadPoolExecutor(max_workers=16) as pool:
  start=time.perf_counter();ptx=gpu.compile(ROOT/'tools/gpu_status_probe.cu');compile_seconds=time.perf_counter()-start
  for kind,name in [(0,'status_batch'),(1,'pool_batch')]:
   for steps in (30,180):
    for count in (8,32,128,512,2048,8192):
     width=11 if kind==0 else 12;rng=random.Random(19531);inputs=(c.c_double*(count*2))()
     for i in range(count):
      absence=rng.uniform(.02,.99);inputs[2*i]=absence;inputs[2*i+1]=(1-absence)*rng.uniform(.2,3.)
     expected=(c.c_double*(count*width))();actual=(c.c_double*(count*width))();parallel=(c.c_double*(count*width))()
     din=gpu.allocate(c.sizeof(inputs));dout=gpu.allocate(c.sizeof(actual))
     timings={str(n):[] for n in (1,8,16)};costs={str(n):[] for n in (1,8,16)};gt=[];kt=[];ut=[];dt=[]
     for repeat in range(args.repeats+1):
      for workers in (1,8,16):
       start=time.perf_counter();pc=time.process_time()
       if workers==1:cpu.bench(inputs,expected,count,steps,0,kind)
       else:
        chunk=(count+workers-1)//workers;futures=[]
        for begin in range(0,count,chunk):
         n=min(chunk,count-begin)
         futures.append(pool.submit(cpu.bench,c.byref(inputs,begin*16),c.byref(parallel,begin*width*8),n,steps,begin,kind))
        for f in futures:f.result()
       wall=time.perf_counter()-start;process=time.process_time()-pc
       if workers>1:assert bytes(parallel)==bytes(expected)
       if repeat:timings[str(workers)].append(wall);costs[str(workers)].append(process)
      start=time.perf_counter();gpu.upload(din,inputs);uploaded=time.perf_counter()
      gpu.launch(name,count,[din,dout,c.c_int(count),c.c_int(steps)]);gpu.synchronize();ran=time.perf_counter()
      gpu.download(actual,dout);end=time.perf_counter()
      assert bytes(actual)==bytes(expected),(name,count,steps,max(abs(a-b) for a,b in zip(actual,expected)))
      if repeat:gt.append(end-start);kt.append(ran-uploaded);ut.append(uploaded-start);dt.append(end-ran)
     row=dict(kernel=name,steps=steps,candidates=count,exact=True,cpuWall={k:statistics.median(v) for k,v in timings.items()},cpuProcess={k:statistics.median(v) for k,v in costs.items()},gpuRoundtrip=statistics.median(gt),gpuKernelSync=statistics.median(kt),upload=statistics.median(ut),download=statistics.median(dt))
     rows.append(row);print(json.dumps(row),flush=True)
  result=dict(device=gpu.name,architecture=gpu.arch,options=gpu.options,compileSeconds=compile_seconds,loadBefore=before,loadAfter=load(),scope='isolated proc recurrence and bounded live pool; not candidate scoring',rows=rows,sourceSha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'tools/gpu_status_probe.cu',ROOT/'native/wfcore/src/proc.rs',source]},ptxSha256=hashlib.sha256(ptx).hexdigest())
 (out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

if __name__=='__main__':main()
