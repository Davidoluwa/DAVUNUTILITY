// Read bandwidth vs working-set size and thread count.
// Decode speed is bounded by how fast we can stream weights, so this is the roofline.
#define _GNU_SOURCE
#include <immintrin.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct {
    const uint8_t *p;
    size_t n;
    int reps;
    __m512i acc;
} job_t;

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

static void *run(void *arg) {
    job_t *j = arg;
    __m512i a0 = _mm512_setzero_si512(), a1 = a0, a2 = a0, a3 = a0;
    for (int r = 0; r < j->reps; r++) {
        for (size_t i = 0; i < j->n; i += 256) {
            a0 = _mm512_xor_si512(a0, _mm512_load_si512(j->p + i));
            a1 = _mm512_xor_si512(a1, _mm512_load_si512(j->p + i + 64));
            a2 = _mm512_xor_si512(a2, _mm512_load_si512(j->p + i + 128));
            a3 = _mm512_xor_si512(a3, _mm512_load_si512(j->p + i + 192));
        }
    }
    j->acc = _mm512_xor_si512(_mm512_xor_si512(a0, a1), _mm512_xor_si512(a2, a3));
    return NULL;
}

static double bench(uint8_t *buf, size_t total, int nth) {
    pthread_t th[64];
    job_t jobs[64];
    size_t per = (total / nth) & ~(size_t)255;
    int reps = (int)(4e9 / total);
    if (reps < 2) reps = 2;
    for (int t = 0; t < nth; t++) jobs[t] = (job_t){buf + t * per, per, 1, _mm512_setzero_si512()};
    for (int t = 0; t < nth; t++) pthread_create(&th[t], NULL, run, &jobs[t]);  // warm
    for (int t = 0; t < nth; t++) pthread_join(th[t], NULL);
    for (int t = 0; t < nth; t++) jobs[t].reps = reps;
    double t0 = now();
    for (int t = 0; t < nth; t++) pthread_create(&th[t], NULL, run, &jobs[t]);
    for (int t = 0; t < nth; t++) pthread_join(th[t], NULL);
    double dt = now() - t0;
    return (double)per * nth * reps / dt / 1e9;
}

int main(void) {
    size_t sizes[] = {1 << 20, 4 << 20, 32 << 20, 128 << 20, 512ull << 20, 2048ull << 20};
    size_t maxsz = sizes[5];
    uint8_t *buf = aligned_alloc(4096, maxsz);
    memset(buf, 1, maxsz);
    printf("%-10s %10s %10s %10s %10s\n", "set", "1 thr", "2 thr", "3 thr", "4 thr");
    for (int s = 0; s < 6; s++) {
        printf("%-7zu MB", sizes[s] >> 20);
        for (int nth = 1; nth <= 4; nth++) printf(" %5.1f GB/s", bench(buf, sizes[s], nth));
        printf("\n");
    }
    return 0;
}
