// Dump a GGUF and compute the per-token byte budget: the number that decides decode speed.
//   inspect MODEL.gguf [dram_GBps] [disk_GBps]
#include <cstdio>
#include <cstdlib>
#include <map>
#include <regex>
#include <string>

#include "../src/gguf.h"

using namespace fl;

static std::string category(const std::string &n) {
    if (n.rfind("token_embd", 0) == 0) return "embed (1 row/token)";
    if (n.rfind("output.", 0) == 0 && n.find("norm") == std::string::npos) return "lm head";
    if (n.find("_exps") != std::string::npos) return "routed experts";
    if (n.find("_shexp") != std::string::npos) return "shared expert";
    if (n.find("ffn_gate_inp") != std::string::npos || n.find("exp_probs") != std::string::npos) return "router";
    if (n.find("attn_") != std::string::npos && n.find("norm") == std::string::npos && n.find("sinks") == std::string::npos)
        return "attention proj";
    if (n.find("ffn_") != std::string::npos && n.find("norm") == std::string::npos) return "dense ffn";
    return "norms/misc";
}

int main(int argc, char **argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s MODEL.gguf [dram_GBps=43] [disk_GBps=3]\n", argv[0]);
        return 1;
    }
    double dram = argc > 2 ? std::atof(argv[2]) : 43.0, disk = argc > 3 ? std::atof(argv[3]) : 3.0;
    GGUF g(argv[1]);
    std::string arch = g.get_str("general.architecture", "?");
    std::printf("GGUF v%u  arch=%s  tensors=%zu  file=%.2f GB\n\n", g.version, arch.c_str(), g.tensors.size(),
                g.file_size / 1e9);

    std::printf("== metadata\n");
    for (auto &[k, v] : g.kvs) {
        if (v.type == GVal::ARR)
            std::printf("  %-48s [array of %llu]\n", k.c_str(), (unsigned long long)v.arr_n);
        else if (v.type == GVal::STR)
            std::printf("  %-48s %.80s\n", k.c_str(), v.s.c_str());
        else if (v.type == GVal::F32 || v.type == GVal::F64)
            std::printf("  %-48s %g\n", k.c_str(), v.f);
        else
            std::printf("  %-48s %lld\n", k.c_str(), (long long)v.i);
    }

    int64_t top_k = g.get_int(arch + ".expert_used_count", 0);

    // Group "blk.17.attn_q.weight" -> "blk.#.attn_q.weight" with its type mix.
    struct Grp { int n = 0; uint64_t bytes = 0; int64_t elems = 0; std::map<std::string, int> types; std::string shape; };
    std::map<std::string, Grp> groups;
    std::regex blk("blk\\.[0-9]+\\.");
    for (auto &t : g.tensors) {
        auto &gr = groups[std::regex_replace(t.name, blk, "blk.#.")];
        gr.n++;
        gr.bytes += t.nbytes;
        gr.elems += t.nelem();
        gr.types[ggml_type_name(t.type)]++;
        if (gr.shape.empty())
            for (size_t d = 0; d < t.dims.size(); d++) gr.shape += (d ? "x" : "") + std::to_string(t.dims[d]);
    }
    std::printf("\n== tensors (grouped)\n  %-34s %4s %-18s %10s %6s  %s\n", "name", "n", "shape", "GB", "bpw", "types");
    for (auto &[name, gr] : groups) {
        std::string ty;
        for (auto &[tn, c] : gr.types) ty += tn + "x" + std::to_string(c) + " ";
        std::printf("  %-34s %4d %-18s %10.3f %6.2f  %s\n", name.c_str(), gr.n, gr.shape.c_str(), gr.bytes / 1e9,
                    8.0 * gr.bytes / gr.elems, ty.c_str());
    }

    // Bytes that must stream per decoded token (batch 1, no reuse across tokens).
    std::map<std::string, std::pair<double, double>> cat;  // total bytes, bytes per token
    for (auto &t : g.tensors) {
        std::string c = category(t.name);
        double per = double(t.nbytes);
        if (c.rfind("embed", 0) == 0) per = double(t.nbytes) / double(t.dims.back());
        if (c == "routed experts" && t.dims.size() == 3 && top_k > 0) per = double(t.nbytes) / t.dims[2] * top_k;
        cat[c].first += t.nbytes;
        cat[c].second += per;
    }
    double tot = 0, per_tok = 0, always = 0, routed = 0;
    std::printf("\n== per-token traffic (top_k=%lld)\n  %-22s %10s %14s\n", (long long)top_k, "category", "total GB",
                "MB/token");
    for (auto &[c, v] : cat) {
        std::printf("  %-22s %10.3f %14.1f\n", c.c_str(), v.first / 1e9, v.second / 1e6);
        tot += v.first;
        per_tok += v.second;
        if (c == "routed experts") routed += v.second;
        else if (c.rfind("embed", 0) != 0) always += v.second;
    }
    std::printf("  %-22s %10.3f %14.1f\n", "TOTAL", tot / 1e9, per_tok / 1e6);
    std::printf("\n  always-active set (resident): %.1f MB/token, %.2f GB resident\n", always / 1e6,
                (cat["attention proj"].first + cat["shared expert"].first + cat["router"].first + cat["dense ffn"].first +
                 cat["lm head"].first + cat["norms/misc"].first) / 1e9);
    std::printf("  routed experts:               %.1f MB/token\n", routed / 1e6);
    std::printf("\n== decode ceilings (bandwidth only, batch 1)\n");
    std::printf("  all weights in DRAM @ %.0f GB/s:          %6.1f tok/s\n", dram, dram * 1e9 / per_tok);
    for (double hit : {0.0, 0.5, 0.8, 0.9}) {
        double miss = routed * (1 - hit);
        double t = always / (dram * 1e9) + routed * hit / (dram * 1e9) + miss / (disk * 1e9);
        std::printf("  experts on disk @ %.1f GB/s, cache hit %3.0f%%: %6.1f tok/s\n", disk, hit * 100, 1 / t);
    }
    return 0;
}
