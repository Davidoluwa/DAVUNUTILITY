// Fixed-budget cache of routed experts, filled with direct (O_DIRECT) reads from the GGUF.
// This is what keeps RAM bounded: experts never go through the OS page cache, and only
// `slots` of them (out of layers x 256) are in memory at any time.
//
// Loads are asynchronous: prefetch() starts reads for experts predicted for an upcoming layer,
// and acquire() only waits for whatever is still in flight. All bookkeeping happens on the
// calling thread; I/O workers only fill memory and count down a per-slot counter.
#pragma once
#include <array>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <list>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "gguf.h"

namespace fl {

// Blocking worker pool for disk reads (threads sleep in pread, so they cost no CPU).
class IoQueue {
public:
    explicit IoQueue(int n);
    ~IoQueue();
    void submit(std::function<void()> job);

private:
    void loop();
    std::vector<std::thread> threads_;
    std::mutex mu_;
    std::condition_variable cv_;
    std::deque<std::function<void()>> q_;
    bool stop_ = false;
};

struct ExpertView {
    const uint8_t *gate, *up, *down;
};

struct CacheStats {
    uint64_t hits = 0;           // ready when needed
    uint64_t prefetch_hits = 0;  // loaded (or loading) because of a prefetch
    uint64_t misses = 0;         // had to be loaded on demand
    uint64_t prefetched = 0, prefetch_unused = 0;  // prefetches issued / evicted without being used
    uint64_t bytes_read = 0;
    double wait_seconds = 0;  // time acquire() spent waiting on disk
};

class ExpertCache {
public:
    // layers: indices of the MoE layers. budget_bytes: memory for expert slots.
    ExpertCache(const std::string &path, const GGUF &g, const std::vector<int> &layers, size_t budget_bytes,
                int io_threads = 8);
    ~ExpertCache();

    // True when the expert is loaded or already on its way.
    bool resident(int layer, int expert) const;
    // Start loading any of these experts that are absent. Returns the number of loads started.
    int prefetch(int layer, const int *experts, int n);
    // Make the experts resident (loading misses) and return their weights once all are in memory.
    void acquire(int layer, const int *experts, int n, ExpertView *out);

    size_t slots() const { return n_slots_; }
    size_t slot_bytes() const { return slot_bytes_; }
    CacheStats stats;

private:
    struct Slice {
        uint64_t offset;  // file offset of expert 0's slice
        uint64_t len;     // bytes per expert
    };
    struct Slot {
        uint32_t key = UINT32_MAX;
        const uint8_t *ptr[3] = {};
        std::atomic<int> pending{0};  // reads still in flight
        bool prefetched = false, used = false;
    };
    static uint32_t key(int layer, int e) { return uint32_t(layer) << 16 | uint32_t(e); }
    size_t load(int layer, int e, bool prefetch, const std::vector<size_t> &pinned);

    int fd_ = -1;
    std::unordered_map<int, std::array<Slice, 3>> slices_;  // per layer: gate, up, down
    size_t slot_bytes_ = 0, n_slots_ = 0;
    std::array<size_t, 3> part_stride_{};
    uint8_t *mem_ = nullptr;
    size_t mem_len_ = 0;
    std::unique_ptr<Slot[]> slot_;
    std::unordered_map<uint32_t, size_t> where_;  // key -> slot
    std::list<size_t> lru_;                       // front = most recently used
    std::vector<std::list<size_t>::iterator> lru_pos_;
    IoQueue io_;
};

}  // namespace fl
