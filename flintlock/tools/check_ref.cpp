// Compare flintlock against reference outputs from llama.cpp (worker B's testdata).
// Input is the plain-text form written by tools/ref_to_txt.py:
//   line 1: prompt ids; line 2: greedy ids; then per checked step: "step id:logit id:logit ..."
//   check_ref -m MODEL REF.txt [--ram-gb 4 --prefetch 10]
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "../src/expert_cache.h"
#include "../src/gguf.h"
#include "../src/model.h"

using namespace fl;

static std::vector<int> ints(const std::string &line) {
    std::istringstream s(line);
    std::vector<int> v;
    for (int x; s >> x;) v.push_back(x);
    return v;
}

static long rss_mb() {
    std::ifstream f("/proc/self/status");
    std::string line;
    while (std::getline(f, line))
        if (line.rfind("VmRSS:", 0) == 0) return std::atol(line.c_str() + 6) / 1024;
    return 0;
}

int main(int argc, char **argv) {
    std::string model, ref;
    float ram_gb = 0;
    int prefetch = 0;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "-m") model = argv[++i];
        else if (a == "--ram-gb") ram_gb = std::atof(argv[++i]);
        else if (a == "--prefetch") prefetch = std::atoi(argv[++i]);
        else ref = a;
    }
    std::ifstream in(ref);
    std::string l1, l2, line;
    std::getline(in, l1);
    std::getline(in, l2);
    const std::vector<int> prompt = ints(l1), greedy = ints(l2);
    struct Step { int step; std::vector<int> ids; std::vector<float> logits; };
    std::vector<Step> steps;
    while (std::getline(in, line)) {
        std::istringstream s(line);
        Step st;
        s >> st.step;
        for (std::string tok; s >> tok;) {
            st.ids.push_back(std::atoi(tok.c_str()));
            st.logits.push_back(std::atof(tok.substr(tok.find(':') + 1).c_str()));
        }
        steps.push_back(st);
    }

    GGUF g(model);
    ThreadPool pool(4);
    Flint m(g, int(prompt.size() + greedy.size()) + 8, pool);
    m.prefetch_n = prefetch;
    std::unique_ptr<ExpertCache> cache;
    if (ram_gb > 0) {
        g.drop_page_cache();
        cache = std::make_unique<ExpertCache>(model, g, m.moe_layers(),
                                              size_t(ram_gb * 1e9 - (rss_mb() + 150.0) * 1048576.0));
        m.set_expert_cache(cache.get());
    }

    int pos = 0;
    const float *lg = nullptr;
    for (int id : prompt) lg = m.forward(id, pos++);
    const int64_t V = m.config().n_vocab;
    int first_diff = -1;
    double worst_logit = 0;
    int rank_match = 0, rank_total = 0;
    for (size_t t = 0; t < greedy.size(); t++) {
        for (const Step &st : steps) {
            if (st.step != int(t)) continue;
            for (size_t k = 0; k < st.ids.size(); k++) worst_logit = std::max(worst_logit, double(std::fabs(lg[st.ids[k]] - st.logits[k])));
            std::vector<int> idx(V);
            for (int64_t v = 0; v < V; v++) idx[v] = int(v);
            std::partial_sort(idx.begin(), idx.begin() + long(st.ids.size()), idx.end(), [&](int a, int b) { return lg[a] > lg[b]; });
            for (size_t k = 0; k < st.ids.size(); k++) rank_match += idx[k] == st.ids[k];
            rank_total += int(st.ids.size());
        }
        const int ours = int(std::max_element(lg, lg + V) - lg);
        if (ours != greedy[t] && first_diff < 0) first_diff = int(t);
        lg = m.forward(greedy[t], pos++);  // teacher-force the reference so later steps stay comparable
    }
    std::printf("%s: prompt %zu tok, greedy %s (%zu tokens), top-10 rank match %d/%d, max |logit diff| %.3f\n",
                ref.c_str(), prompt.size(), first_diff < 0 ? "IDENTICAL" : ("diverges at " + std::to_string(first_diff)).c_str(),
                greedy.size(), rank_match, rank_total, worst_logit);
    return first_diff < 0 ? 0 : 1;
}
