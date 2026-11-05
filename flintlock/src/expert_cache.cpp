#include "expert_cache.h"

#include <fcntl.h>
#include <immintrin.h>
#include <sys/mman.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>

namespace fl {

namespace {
constexpr size_t kAlign = 4096;  // O_DIRECT offset/length granularity
double now() { return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
}  // namespace

// ---------------------------------------------------------------- IoQueue

IoQueue::IoQueue(int n) {
    for (int i = 0; i < n; i++) threads_.emplace_back([this] { loop(); });
}
IoQueue::~IoQueue() {
    {
        std::lock_guard<std::mutex> l(mu_);
        stop_ = true;
    }
    cv_.notify_all();
    for (auto &t : threads_) t.join();
}
void IoQueue::submit(std::function<void()> job) {
    {
        std::lock_guard<std::mutex> l(mu_);
        q_.push_back(std::move(job));
    }
    cv_.notify_one();
}
void IoQueue::loop() {
    for (;;) {
        std::function<void()> job;
        {
            std::unique_lock<std::mutex> l(mu_);
            cv_.wait(l, [&] { return stop_ || !q_.empty(); });
            if (q_.empty()) return;  // stop requested and nothing left
            job = std::move(q_.front());
            q_.pop_front();
        }
        job();
    }
}

// ---------------------------------------------------------------- ExpertCache

ExpertCache::ExpertCache(const std::string &path, const GGUF &g, const std::vector<int> &layers, size_t budget_bytes,
                         int io_threads)
    : io_(io_threads) {
    fd_ = ::open(path.c_str(), O_RDONLY | O_DIRECT);
    if (fd_ < 0) throw std::runtime_error("expert cache: cannot open with O_DIRECT");

    const char *names[3] = {"ffn_gate_exps", "ffn_up_exps", "ffn_down_exps"};
    for (int il : layers) {
        std::array<Slice, 3> s{};
        for (int k = 0; k < 3; k++) {
            const Tensor *t = g.tensor("blk." + std::to_string(il) + "." + names[k] + ".weight");
            if (!t || t->dims.size() != 3) throw std::runtime_error("expert cache: bad expert tensor");
            s[k].offset = g.data_offset + t->offset;
            s[k].len = t->nbytes / uint64_t(t->dims[2]);
        }
        slices_[il] = s;
    }
    // Each slice gets room for alignment slack at both ends.
    for (int k = 0; k < 3; k++) {
        part_stride_[k] = (slices_.begin()->second[k].len + 3 * kAlign - 1) / kAlign * kAlign;
        slot_bytes_ += part_stride_[k];
    }
    n_slots_ = budget_bytes / slot_bytes_;
    if (n_slots_ < 16) throw std::runtime_error("expert cache: budget too small");

    mem_len_ = n_slots_ * slot_bytes_;
    void *m = mmap(nullptr, mem_len_, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (m == MAP_FAILED) throw std::runtime_error("expert cache: mmap failed");
    mem_ = static_cast<uint8_t *>(m);
    madvise(mem_, mem_len_, MADV_HUGEPAGE);

    slot_.reset(new Slot[n_slots_]);
    lru_pos_.resize(n_slots_);
    for (size_t i = 0; i < n_slots_; i++) lru_pos_[i] = lru_.insert(lru_.end(), i);
}

ExpertCache::~ExpertCache() {
    // Let in-flight reads finish before the memory goes away.
    for (size_t i = 0; i < n_slots_; i++)
        while (slot_[i].pending.load(std::memory_order_acquire) > 0) _mm_pause();
    if (mem_) munmap(mem_, mem_len_);
    if (fd_ >= 0) ::close(fd_);
}

bool ExpertCache::resident(int layer, int e) const { return where_.count(key(layer, e)) != 0; }

// Claim the least recently used slot that is idle and not pinned, and start reading into it.
size_t ExpertCache::load(int layer, int e, bool prefetch, const std::vector<size_t> &pinned) {
    auto victim = std::prev(lru_.end());
    while (slot_[*victim].pending.load(std::memory_order_acquire) > 0 ||
           std::find(pinned.begin(), pinned.end(), *victim) != pinned.end()) {
        if (victim == lru_.begin()) throw std::runtime_error("expert cache: every slot is busy");
        victim = std::prev(victim);
    }
    const size_t s = *victim;
    Slot &sl = slot_[s];
    if (sl.key != UINT32_MAX) {
        where_.erase(sl.key);
        if (sl.prefetched && !sl.used) stats.prefetch_unused++;
    }
    sl.key = key(layer, e);
    sl.prefetched = prefetch;
    sl.used = false;
    where_[sl.key] = s;

    const auto &parts = slices_.at(layer);
    uint8_t *base = mem_ + s * slot_bytes_;
    sl.pending.store(3, std::memory_order_release);
    for (int k = 0; k < 3; k++) {
        const uint64_t off = parts[k].offset + uint64_t(e) * parts[k].len;
        const uint64_t a0 = off / kAlign * kAlign;
        const uint64_t a1 = (off + parts[k].len + kAlign - 1) / kAlign * kAlign;
        sl.ptr[k] = base + (off - a0);
        stats.bytes_read += a1 - a0;
        std::atomic<int> *pend = &sl.pending;
        io_.submit([this, base, a0, a1, pend] {
            size_t done = 0;
            while (done < a1 - a0) {
                ssize_t r = pread(fd_, base + done, a1 - a0 - done, off_t(a0 + done));
                if (r <= 0) {
                    std::perror("expert cache: pread");
                    std::abort();
                }
                done += size_t(r);
            }
            pend->fetch_sub(1, std::memory_order_acq_rel);
        });
        base += part_stride_[k];
    }
    return s;
}

int ExpertCache::prefetch(int layer, const int *experts, int n) {
    int started = 0;
    static const std::vector<size_t> none;
    for (int i = 0; i < n; i++) {
        if (resident(layer, experts[i])) continue;
        const size_t s = load(layer, experts[i], true, none);
        lru_.splice(lru_.begin(), lru_, lru_pos_[s]);  // keep it until the layer runs
        stats.prefetched++;
        started++;
    }
    return started;
}

void ExpertCache::acquire(int layer, const int *experts, int n, ExpertView *out) {
    std::vector<size_t> pinned;
    pinned.reserve(size_t(n));
    for (int i = 0; i < n; i++) {
        auto it = where_.find(key(layer, experts[i]));
        size_t s;
        if (it == where_.end()) {
            stats.misses++;
            s = load(layer, experts[i], false, pinned);
        } else {
            s = it->second;
            if (slot_[s].prefetched && !slot_[s].used) stats.prefetch_hits++;
            else stats.hits++;
        }
        slot_[s].used = true;
        lru_.splice(lru_.begin(), lru_, lru_pos_[s]);
        pinned.push_back(s);
    }
    const double t0 = now();
    for (int i = 0; i < n; i++) {
        Slot &sl = slot_[pinned[size_t(i)]];
        while (sl.pending.load(std::memory_order_acquire) > 0) _mm_pause();
        out[i] = {sl.ptr[0], sl.ptr[1], sl.ptr[2]};
    }
    stats.wait_seconds += now() - t0;
}

}  // namespace fl
