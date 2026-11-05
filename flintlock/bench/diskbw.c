// Disk read speed with the page cache bypassed (O_DIRECT).
// Models streaming MoE expert slices from SSD: random reads of `chunk` bytes at a
// given queue depth (one thread per outstanding read).
#define _GNU_SOURCE
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static int fd;
static off_t fsize;
static size_t chunk;
static int seconds = 3;
static volatile int stop_flag;

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

typedef struct { uint64_t bytes, ops; unsigned seed; int sequential; off_t pos; } st_t;

static void *worker(void *arg) {
    st_t *s = arg;
    void *buf;
    if (posix_memalign(&buf, 4096, chunk)) return NULL;
    while (!stop_flag) {
        off_t off;
        if (s->sequential) {
            off = s->pos;
            s->pos += chunk;
            if (s->pos + (off_t)chunk > fsize) s->pos = 0;
        } else {
            off = ((off_t)rand_r(&s->seed) * 4096) % (fsize - chunk);
            off &= ~(off_t)4095;
        }
        ssize_t r = pread(fd, buf, chunk, off);
        if (r <= 0) break;
        s->bytes += r;
        s->ops++;
    }
    free(buf);
    return NULL;
}

static void run(int qd, int seq) {
    pthread_t th[64];
    st_t st[64];
    stop_flag = 0;
    for (int i = 0; i < qd; i++) {
        st[i] = (st_t){0, 0, 1234u + i, seq, (fsize / qd * i) & ~(off_t)4095};
        pthread_create(&th[i], NULL, worker, &st[i]);
    }
    double t0 = now();
    sleep(seconds);
    stop_flag = 1;
    uint64_t b = 0, o = 0;
    for (int i = 0; i < qd; i++) {
        pthread_join(th[i], NULL);
        b += st[i].bytes;
        o += st[i].ops;
    }
    double dt = now() - t0;
    printf("%-10s chunk=%6zu KB qd=%2d  %7.2f GB/s  %8.0f IOPS  %6.2f ms/op\n", seq ? "sequential" : "random",
           chunk >> 10, qd, b / dt / 1e9, o / dt, dt * 1e3 * qd / (o ? o : 1));
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s FILE\n", argv[0]); return 1; }
    fd = open(argv[1], O_RDONLY | O_DIRECT);
    if (fd < 0) { perror("open O_DIRECT"); return 1; }
    struct stat sb;
    fstat(fd, &sb);
    fsize = sb.st_size;
    size_t chunks[] = {256 << 10, 1 << 20, 4 << 20};
    int qds[] = {1, 4, 16, 32};
    for (int c = 0; c < 3; c++) {
        chunk = chunks[c];
        for (int q = 0; q < 4; q++) run(qds[q], 0);
    }
    chunk = 4 << 20;
    run(4, 1);
    return 0;
}
