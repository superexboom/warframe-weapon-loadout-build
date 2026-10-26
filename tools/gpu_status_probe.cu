// Exact operation-order prototype of proc::arrival_kernel + proc::fold.
// One thread owns one independent status-distribution recurrence.
extern "C" __global__ void status_batch(const double* input, double* output, int count, int steps) {
    int lane = blockIdx.x * blockDim.x + threadIdx.x;
    if (lane >= count) return;
    double absence = input[lane * 2], expected = input[lane * 2 + 1];
    double p = fmin(1.0, fmax(0.0, 1.0 - absence));
    int shifts[3], used = 0;
    double weights[3], dist[11] = {1.0}, next[11];
    if (p > 0.0 && expected > 0.0) {
        double size = expected / p;
        int low = (int)floor(size + 1e-9);
        double frac = fmax(0.0, size - low);
        int raw_shifts[3] = {0, low, low + 1};
        double raw_weights[3] = {1.0 - p, p * (1.0 - frac), p * frac};
        for (int j = 0; j < 3; ++j) if (raw_weights[j] > 0.0) {
            int key = min(max(raw_shifts[j], 0), 10), at = 0;
            while (at < used && shifts[at] != key) ++at;
            if (at == used) { shifts[used] = key; weights[used++] = raw_weights[j]; }
            else weights[at] += raw_weights[j];
        }
        for (int event = 0; event < steps; ++event) {
            for (int k = 0; k <= 10; ++k) next[k] = 0.0;
            for (int j = 0; j < used; ++j)
                for (int k = 0; k <= 10; ++k)
                    if (dist[k] != 0.0) next[min(k + shifts[j], 10)] += weights[j] * dist[k];
            for (int k = 0; k <= 10; ++k) dist[k] = next[k];
        }
    }
    for (int k = 0; k <= 10; ++k) output[lane * 11 + k] = dist[k];
}


// Bounded form of the production two-stack CappedPool. Supports expiry,
// changing arrivals, target resets and a distribution query at every event.
// The bound is part of this experiment, not a general replay admission rule.
struct Arrival { int shifts[3], used; double weights[3]; };
__device__ Arrival arrival(double absence, double expected) {
    Arrival a; a.used = 0;
    double p = fmin(1.0, fmax(0.0, 1.0 - absence));
    if (p <= 0.0 || expected <= 0.0) return a;
    double size = expected / p;
    int low = (int)floor(size + 1e-9);
    double fraction = fmax(0.0, size - low);
    int shifts[3] = {0, low, low + 1};
    double weights[3] = {1-p, p*(1-fraction), p*fraction};
    for(int j=0;j<3;++j) if(weights[j]>0) {
        int key=min(max(shifts[j],0),10), at=0;
        while(at<a.used && a.shifts[at]!=key)++at;
        if(at==a.used){a.shifts[at]=key;a.weights[at]=weights[j];++a.used;}
        else a.weights[at]+=weights[j];
    }
    return a;
}
__device__ void fold_pool(double* dist, const Arrival& a) {
    double next[11]={0};
    for(int j=0;j<a.used;++j)for(int k=0;k<11;++k)
        if(dist[k]!=0)next[min(k+a.shifts[j],10)]+=a.weights[j]*dist[k];
    for(int k=0;k<11;++k)dist[k]=next[k];
}
extern "C" __global__ void pool_batch(const double* input,double* output,int count,int steps) {
    int lane=blockIdx.x*blockDim.x+threadIdx.x;
    if(lane>=count)return;
    Arrival back[64]; double ends[64], front_end[64], front_dist[64][11];
    double back_dist[11]={1},dist[11]={1},checksum=0;
    int nf=0,nb=0;
    double absence=input[lane*2],expected=input[lane*2+1];
    double lifetime=(10+lane%30)*.1;
    for(int event=0;event<steps;++event) {
        double t=event*.1;
        if(event && event%(37+lane%23)==0){nf=nb=0;for(int k=0;k<11;++k)back_dist[k]=k==0?1:0;}
        while(true){
            if(nf==0){
                if(nb==0 || ends[0]>=t-1e-9)break;
                double accumulated[11]={1};
                while(nb){--nb;fold_pool(accumulated,back[nb]);front_end[nf]=ends[nb];
                    for(int k=0;k<11;++k)front_dist[nf][k]=accumulated[k];++nf;}
                for(int k=0;k<11;++k)back_dist[k]=k==0?1:0;
            }
            if(front_end[nf-1]>=t-1e-9)break;
            --nf;
        }
        Arrival a=arrival(absence*(1+event%7)/8.,expected*(1+(event%5)*.25));
        if(a.used){if(nb>=64){output[lane*12]=0./0.;return;}fold_pool(back_dist,a);back[nb]=a;ends[nb++]=t+lifetime;}
        if(nf==0){for(int k=0;k<11;++k)dist[k]=back_dist[k];}
        else{
            for(int k=0;k<11;++k)dist[k]=0;
            for(int i=0;i<11;++i)if(front_dist[nf-1][i]!=0)
                for(int j=0;j<11;++j)if(back_dist[j]!=0)dist[min(i+j,10)]+=front_dist[nf-1][i]*back_dist[j];
        }
        for(int k=0;k<11;++k)checksum+=k*dist[k];
    }
    for(int k=0;k<11;++k)output[lane*12+k]=dist[k];
    output[lane*12+11]=checksum;
}
