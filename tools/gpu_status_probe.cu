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
