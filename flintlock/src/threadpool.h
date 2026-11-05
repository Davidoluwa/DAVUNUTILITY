// Spin-waiting thread pool. A decode step issues hundreds of small parallel ops, so wake-up
// latency matters more than idle CPU: workers spin on a generation counter instead of sleeping.
#pragma once
#include <immintrin.h>

#include <atomic>
#include <cstdint>
#include <functional>
#include <thread>
#include <vector>

namespace fl {

class ThreadPool {
public:
    explicit ThreadPool(int n_threads) : n_(n_threads < 1 ? 1 : n_threads) {
        for (int t = 1; t < n_; t++) workers_.emplace_back([this, t] { loop(t); });
    }
    ~ThreadPool() {
        stop_.store(true);
        gen_.fetch_add(1);
        for (auto &w : workers_) w.join();
    }
    int size() const { return n_; }

    // Run f(thread_id, n_threads) on every thread, the caller included, and wait for all.
    void run(const std::function<void(int, int)> &f) {
        if (n_ == 1) {
            f(0, 1);
            return;
        }
        job_ = &f;
        pending_.store(n_ - 1, std::memory_order_relaxed);
        gen_.fetch_add(1, std::memory_order_release);
        f(0, n_);
        while (pending_.load(std::memory_order_acquire) != 0) _mm_pause();
    }

    // Split [0, n) into one contiguous range per thread: f(begin, end, thread_id).
    template <class F>
    void parallel_for(int64_t n, F &&f) {
        run([&](int t, int nt) {
            int64_t b = n * t / nt, e = n * (t + 1) / nt;
            if (b < e) f(b, e, t);
        });
    }

    // Hand out [0, n) in chunks through an atomic counter: for rows of uneven cost.
    template <class F>
    void parallel_for_dynamic(int64_t n, int64_t chunk, F &&f) {
        std::atomic<int64_t> next{0};
        run([&](int t, int) {
            for (;;) {
                const int64_t b = next.fetch_add(chunk, std::memory_order_relaxed);
                if (b >= n) break;
                f(b, b + chunk < n ? b + chunk : n, t);
            }
        });
    }

private:
    void loop(int t) {
        uint64_t seen = 0;
        for (;;) {
            uint64_t g;
            int spins = 0;
            while ((g = gen_.load(std::memory_order_acquire)) == seen) {
                if (++spins < 1 << 16) _mm_pause();
                else std::this_thread::yield();
            }
            seen = g;
            if (stop_.load()) return;
            (*job_)(t, n_);
            pending_.fetch_sub(1, std::memory_order_acq_rel);
        }
    }

    int n_;
    std::vector<std::thread> workers_;
    const std::function<void(int, int)> *job_ = nullptr;
    alignas(64) std::atomic<uint64_t> gen_{0};
    alignas(64) std::atomic<int> pending_{0};
    std::atomic<bool> stop_{false};
};

}  // namespace fl
