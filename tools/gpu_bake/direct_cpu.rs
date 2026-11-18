// CPU reference for the same immutable complete event stream.
#[no_mangle]
pub unsafe extern "C" fn direct_batch(damage:*const f64,offsets:*const i32,lengths:*const i32,
    health:*const f64,window:*const f64,output:*mut f64,count:usize) {
    for i in 0..count {
        let hp=*health.add(i);let duration=*window.add(i);
        let mut pool=hp;let mut total=0.0;let mut kills=0i32;
        for j in 0..*lengths.add(i) {
            let requested=*damage.add((*offsets.add(i)+j) as usize);
            let actual=pool.min(requested.max(0.0));pool-=actual;total+=actual;
            if pool<=1e-7 {kills+=1;pool=hp;}
        }
        let score=kills as f64+if hp!=0.0 {1.0-pool/hp}else{0.0};
        *output.add(i*3)=if duration!=0.0 {score*60.0/duration}else{0.0};
        *output.add(i*3+1)=if duration!=0.0 {total/duration}else{0.0};
        *output.add(i*3+2)=total;
    }
}
