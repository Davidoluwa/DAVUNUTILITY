#include "gguf.h"

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <cstring>
#include <stdexcept>

namespace fl {

namespace {

struct Cursor {
    const uint8_t *p, *end;
    void need(size_t n) const {
        if (size_t(end - p) < n) throw std::runtime_error("gguf: truncated header");
    }
    template <class T> T rd() {
        need(sizeof(T));
        T v;
        std::memcpy(&v, p, sizeof(T));
        p += sizeof(T);
        return v;
    }
    std::string str() {
        uint64_t n = rd<uint64_t>();
        need(n);
        std::string s(reinterpret_cast<const char *>(p), n);
        p += n;
        return s;
    }
};

size_t scalar_size(GVal t) {
    switch (t) {
        case GVal::U8: case GVal::I8: case GVal::BOOL: return 1;
        case GVal::U16: case GVal::I16: return 2;
        case GVal::U32: case GVal::I32: case GVal::F32: return 4;
        case GVal::U64: case GVal::I64: case GVal::F64: return 8;
        default: return 0;
    }
}

void read_scalar(Cursor &c, GVal t, KV &kv) {
    switch (t) {
        case GVal::U8: kv.i = c.rd<uint8_t>(); break;
        case GVal::I8: kv.i = c.rd<int8_t>(); break;
        case GVal::U16: kv.i = c.rd<uint16_t>(); break;
        case GVal::I16: kv.i = c.rd<int16_t>(); break;
        case GVal::U32: kv.i = c.rd<uint32_t>(); break;
        case GVal::I32: kv.i = c.rd<int32_t>(); break;
        case GVal::BOOL: kv.i = c.rd<uint8_t>(); break;
        case GVal::U64: kv.i = int64_t(c.rd<uint64_t>()); break;
        case GVal::I64: kv.i = c.rd<int64_t>(); break;
        case GVal::F32: kv.f = c.rd<float>(); kv.i = int64_t(kv.f); return;
        case GVal::F64: kv.f = c.rd<double>(); kv.i = int64_t(kv.f); return;
        case GVal::STR: kv.s = c.str(); return;
        default: throw std::runtime_error("gguf: bad scalar type");
    }
    kv.f = double(kv.i);
}

}  // namespace

GGUF::GGUF(const std::string &path) {
    fd_ = ::open(path.c_str(), O_RDONLY);
    if (fd_ < 0) throw std::runtime_error("gguf: cannot open " + path);
    struct stat sb;
    fstat(fd_, &sb);
    file_size = size_t(sb.st_size);
    void *m = mmap(nullptr, file_size, PROT_READ, MAP_SHARED, fd_, 0);
    if (m == MAP_FAILED) throw std::runtime_error("gguf: mmap failed");
    base = static_cast<const uint8_t *>(m);

    Cursor c{base, base + file_size};
    if (c.rd<uint32_t>() != 0x46554747u) throw std::runtime_error("gguf: bad magic");
    version = c.rd<uint32_t>();
    if (version < 2) throw std::runtime_error("gguf: version < 2 unsupported");
    uint64_t n_tensors = c.rd<uint64_t>();
    uint64_t n_kv = c.rd<uint64_t>();

    kvs.reserve(n_kv);
    for (uint64_t k = 0; k < n_kv; k++) {
        std::string key = c.str();
        KV kv;
        kv.type = GVal(c.rd<uint32_t>());
        if (kv.type == GVal::ARR) {
            kv.arr_type = GVal(c.rd<uint32_t>());
            kv.arr_n = c.rd<uint64_t>();
            kv.arr_data = c.p;
            if (kv.arr_type == GVal::STR) {
                kv.strs.reserve(kv.arr_n);
                for (uint64_t j = 0; j < kv.arr_n; j++) kv.strs.push_back(c.str());
            } else {
                size_t es = scalar_size(kv.arr_type);
                if (!es) throw std::runtime_error("gguf: nested arrays unsupported");
                c.need(es * kv.arr_n);
                c.p += es * kv.arr_n;
            }
        } else {
            read_scalar(c, kv.type, kv);
        }
        kv_idx_[key] = kvs.size();
        kvs.emplace_back(std::move(key), std::move(kv));
    }

    tensors.resize(n_tensors);
    for (auto &t : tensors) {
        t.name = c.str();
        uint32_t nd = c.rd<uint32_t>();
        t.dims.resize(nd);
        for (auto &d : t.dims) d = int64_t(c.rd<uint64_t>());
        t.type = c.rd<uint32_t>();
        t.offset = c.rd<uint64_t>();
    }

    size_t align = size_t(get_int("general.alignment", 32));
    size_t hdr = size_t(c.p - base);
    data_offset = (hdr + align - 1) / align * align;

    // Sizes from offsets: robust to quant types this reader has never heard of.
    std::vector<size_t> order(tensors.size());
    for (size_t i = 0; i < order.size(); i++) order[i] = i;
    std::sort(order.begin(), order.end(), [&](size_t a, size_t b) { return tensors[a].offset < tensors[b].offset; });
    for (size_t k = 0; k < order.size(); k++) {
        Tensor &t = tensors[order[k]];
        uint64_t next = k + 1 < order.size() ? tensors[order[k + 1]].offset : file_size - data_offset;
        t.nbytes = next - t.offset;
        t.data = base + data_offset + t.offset;
        if (data_offset + t.offset + t.nbytes > file_size) throw std::runtime_error("gguf: tensor out of bounds");
    }
    for (size_t i = 0; i < tensors.size(); i++) t_idx_[tensors[i].name] = i;
}

GGUF::~GGUF() {
    if (base) munmap(const_cast<uint8_t *>(base), file_size);
    if (fd_ >= 0) ::close(fd_);
}

const KV *GGUF::get(const std::string &key) const {
    auto it = kv_idx_.find(key);
    return it == kv_idx_.end() ? nullptr : &kvs[it->second].second;
}
int64_t GGUF::get_int(const std::string &key, int64_t def) const {
    auto *kv = get(key);
    return kv ? kv->i : def;
}
double GGUF::get_float(const std::string &key, double def) const {
    auto *kv = get(key);
    return kv ? kv->f : def;
}
std::string GGUF::get_str(const std::string &key, const std::string &def) const {
    auto *kv = get(key);
    return kv && kv->type == GVal::STR ? kv->s : def;
}
const Tensor *GGUF::tensor(const std::string &name) const {
    auto it = t_idx_.find(name);
    return it == t_idx_.end() ? nullptr : &tensors[it->second];
}

const char *ggml_type_name(uint32_t t) {
    switch (t) {
        case 0: return "f32";     case 1: return "f16";     case 2: return "q4_0";    case 3: return "q4_1";
        case 6: return "q5_0";    case 7: return "q5_1";    case 8: return "q8_0";    case 9: return "q8_1";
        case 10: return "q2_K";   case 11: return "q3_K";   case 12: return "q4_K";   case 13: return "q5_K";
        case 14: return "q6_K";   case 15: return "q8_K";   case 16: return "iq2_xxs"; case 17: return "iq2_xs";
        case 18: return "iq3_xxs"; case 19: return "iq1_s";  case 20: return "iq4_nl";  case 21: return "iq3_s";
        case 22: return "iq2_s";  case 23: return "iq4_xs"; case 24: return "i8";      case 25: return "i16";
        case 26: return "i32";    case 27: return "i64";    case 28: return "f64";     case 29: return "iq1_m";
        case 30: return "bf16";   case 34: return "tq1_0";  case 35: return "tq2_0";   case 39: return "mxfp4";
        case 40: return "nvfp4";  case 41: return "q1_0";   case 42: return "q2_0";    case 43: return "f8_e4m3";
        case 64: return "iq1_xs"; case 65: return "iq1_xxs"; case 66: return "iq1_xxxs";
        default: return "?";
    }
}

}  // namespace fl
