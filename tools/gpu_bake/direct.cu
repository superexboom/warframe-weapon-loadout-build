// Exact bounded direct-hit event interpreter. Stateful effects require CPU.
// Inputs: per-event damage is already evaluated against this fixed defense.
// One thread owns a complete fight, target replacement and final partial kill.
extern "C" __global__ void direct_batch(const double* damage, const int* offsets,
    const int* lengths, const double* health, const double* window, double* output,
    const int count) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if(i >= count) return;
    double pool = health[i], total = 0.0;
    int kills = 0;
    for(int j=0;j<lengths[i];++j) {
        double requested = damage[offsets[i]+j];
        double actual = fmin(pool, fmax(0.0, requested));
        pool -= actual;
        total += actual;
        if(pool <= 1e-7) { ++kills; pool = health[i]; }
    }
    double score = (double)kills + (health[i] != 0.0 ? 1.0-pool/health[i] : 0.0);
    output[3*i] = window[i] != 0.0 ? score*60.0/window[i] : 0.0;
    output[3*i+1] = window[i] != 0.0 ? total/window[i] : 0.0;
    output[3*i+2] = total;
}
