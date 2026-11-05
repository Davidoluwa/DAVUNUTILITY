// Minimal zero-copy GGUF reader. The file is mmap'd read-only; tensor data is never
// copied, so the OS decides what is resident. That matters for the RAM budget:
// weights we touch rarely (cold experts) cost page cache, not heap.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace fl {

enum class GVal : uint32_t {
    U8 = 0, I8, U16, I16, U32, I32, F32, BOOL, STR, ARR, U64, I64, F64
};

struct KV {
    GVal type{};
    // Scalars are widened into one of these.
    int64_t i = 0;
    double f = 0;
    std::string s;
    // Arrays: element type, count, and where the raw elements start in the mapping.
    GVal arr_type{};
    uint64_t arr_n = 0;
    const uint8_t *arr_data = nullptr;
    std::vector<std::string> strs;  // filled only for string arrays
};

struct Tensor {
    std::string name;
    std::vector<int64_t> dims;  // ggml order: dims[0] is the contiguous (row) dimension
    uint32_t type = 0;          // ggml_type id
    uint64_t offset = 0;        // relative to data section
    uint64_t nbytes = 0;        // derived from neighbouring offsets
    const uint8_t *data = nullptr;
    int64_t nelem() const {
        int64_t n = 1;
        for (auto d : dims) n *= d;
        return n;
    }
    double bpw() const { return nelem() ? 8.0 * double(nbytes) / double(nelem()) : 0; }
};

class GGUF {
public:
    explicit GGUF(const std::string &path);
    ~GGUF();
    GGUF(const GGUF &) = delete;
    GGUF &operator=(const GGUF &) = delete;

    const KV *get(const std::string &key) const;
    int64_t get_int(const std::string &key, int64_t def) const;
    double get_float(const std::string &key, double def) const;
    std::string get_str(const std::string &key, const std::string &def = "") const;
    const Tensor *tensor(const std::string &name) const;
    // Unmap and evict every page of the file from memory (data stays readable; it refaults).
    void drop_page_cache() const;

    uint32_t version = 0;
    size_t file_size = 0;
    size_t data_offset = 0;
    const uint8_t *base = nullptr;
    std::vector<std::pair<std::string, KV>> kvs;  // file order
    std::vector<Tensor> tensors;                  // file order

private:
    std::unordered_map<std::string, size_t> kv_idx_, t_idx_;
    int fd_ = -1;
};

const char *ggml_type_name(uint32_t t);

}  // namespace fl
