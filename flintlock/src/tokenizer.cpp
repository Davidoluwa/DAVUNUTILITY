#include "tokenizer.h"

#include <algorithm>
#include <cctype>
#include <climits>
#include <cstring>
#include <stdexcept>

#include "unicode_data.h"

namespace fl {

namespace {

// ---------------------------------------------------------------- UTF-8 and Unicode classes

std::vector<uint32_t> utf8_decode(const std::string &s) {
    std::vector<uint32_t> out;
    out.reserve(s.size());
    for (size_t i = 0; i < s.size();) {
        uint8_t c = uint8_t(s[i]);
        uint32_t cp;
        int len;
        if (c < 0x80) cp = c, len = 1;
        else if ((c >> 5) == 6) cp = c & 0x1F, len = 2;
        else if ((c >> 4) == 14) cp = c & 0x0F, len = 3;
        else if ((c >> 3) == 30) cp = c & 0x07, len = 4;
        else cp = 0xFFFD, len = 1;  // stray continuation byte
        if (i + len > s.size()) len = 1, cp = 0xFFFD;
        for (int k = 1; k < len; k++) cp = (cp << 6) | (uint8_t(s[i + k]) & 0x3F);
        out.push_back(cp);
        i += len;
    }
    return out;
}

void utf8_append(std::string &s, uint32_t cp) {
    if (cp < 0x80) s += char(cp);
    else if (cp < 0x800) s += char(0xC0 | (cp >> 6)), s += char(0x80 | (cp & 0x3F));
    else if (cp < 0x10000) s += char(0xE0 | (cp >> 12)), s += char(0x80 | ((cp >> 6) & 0x3F)), s += char(0x80 | (cp & 0x3F));
    else
        s += char(0xF0 | (cp >> 18)), s += char(0x80 | ((cp >> 12) & 0x3F)), s += char(0x80 | ((cp >> 6) & 0x3F)),
            s += char(0x80 | (cp & 0x3F));
}

uint8_t ucd(uint32_t cp) {
    constexpr size_t n = sizeof(k_ucd_start) / sizeof(k_ucd_start[0]);
    size_t i = size_t(std::upper_bound(k_ucd_start, k_ucd_start + n, cp) - k_ucd_start) - 1;
    return k_ucd_class[i];
}
int cat(uint32_t cp) { return ucd(cp) & 15; }
bool is_ws(uint32_t cp) { return (ucd(cp) & 16) != 0; }
bool is_letter(uint32_t cp) { int c = cat(cp); return c >= 1 && c <= 5; }
bool is_number(uint32_t cp) { return cat(cp) == 7; }
bool is_ps(uint32_t cp) { int c = cat(cp); return c == 8 || c == 9; }
// [\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]
bool is_upperish(uint32_t cp) { int c = cat(cp); return c == 1 || c == 3 || c == 4 || c == 5 || c == 6; }
// [\p{Ll}\p{Lm}\p{Lo}\p{M}]
bool is_lowerish(uint32_t cp) { int c = cat(cp); return c == 2 || c == 4 || c == 5 || c == 6; }
bool is_crlf(uint32_t cp) { return cp == '\r' || cp == '\n'; }
// [^\r\n\p{L}\p{N}]
bool is_prefix(uint32_t cp) { return !is_crlf(cp) && !is_letter(cp) && !is_number(cp); }
bool is_cjk(uint32_t cp) {
    return (cp >= 0x4E00 && cp <= 0x9FA5) || (cp >= 0x3040 && cp <= 0x309F) || (cp >= 0x30A0 && cp <= 0x30FF);
}

// ---------------------------------------------------------------- the three split stages
// Each matcher returns the end of a match starting exactly at p, or -1. Order and backtracking
// follow a leftmost-first regex engine (the original tokenizer uses Oniguruma).

using Cps = std::vector<uint32_t>;

long match_digits(const Cps &s, long p, long e) {  // \p{N}{1,3}
    long j = p;
    while (j < e && j - p < 3 && is_number(s[j])) j++;
    return j > p ? j : -1;
}

long match_cjk(const Cps &s, long p, long e) {
    long j = p;
    while (j < e && is_cjk(s[j])) j++;
    return j > p ? j : -1;
}

// (?i:'s|'t|'re|'ve|'m|'ll|'d)
long contraction(const Cps &s, long p, long e) {
    if (p >= e || s[p] != '\'') return p;
    auto lc = [&](long i) -> uint32_t { return i < e && s[i] < 128 ? uint32_t(std::tolower(int(s[i]))) : 0; };
    uint32_t a = lc(p + 1), b = lc(p + 2);
    if (a == 's' || a == 't' || a == 'm' || a == 'd') return p + 2;
    if ((a == 'r' && b == 'e') || (a == 'v' && b == 'e') || (a == 'l' && b == 'l')) return p + 3;
    return p;
}

long match_main(const Cps &s, long p, long e) {
    // 1: [^\r\n\p{L}\p{N}]? [Upper]* [Lower]+ contraction?
    for (int pre = 1; pre >= 0; pre--) {
        if (pre && !(p < e && is_prefix(s[p]))) continue;
        long q = p + pre, j = q;
        while (j < e && is_upperish(s[j])) j++;
        for (long jj = j; jj >= q; jj--) {
            long k = jj;
            while (k < e && is_lowerish(s[k])) k++;
            if (k > jj) return contraction(s, k, e);
        }
    }
    // 2: [^\r\n\p{L}\p{N}]? [Upper]+ [Lower]* contraction?
    for (int pre = 1; pre >= 0; pre--) {
        if (pre && !(p < e && is_prefix(s[p]))) continue;
        long q = p + pre, j = q;
        while (j < e && is_upperish(s[j])) j++;
        if (j == q) continue;
        while (j < e && is_lowerish(s[j])) j++;
        return contraction(s, j, e);
    }
    // 3: ' '? [\p{P}\p{S}]+ [\r\n]*
    for (int sp = 1; sp >= 0; sp--) {
        if (sp && !(p < e && s[p] == ' ')) continue;
        long q = p + sp, j = q;
        while (j < e && is_ps(s[j])) j++;
        if (j == q) continue;
        while (j < e && is_crlf(s[j])) j++;
        return j;
    }
    long j = p;
    while (j < e && is_ws(s[j])) j++;
    if (j == p) return -1;
    // 4: \s*[\r\n]+  -> ends after the last CR/LF inside the whitespace run
    for (long m = j - 1; m >= p; m--)
        if (is_crlf(s[m])) return m + 1;
    // 5: \s+(?!\S)   -> whole run at end of text, else all but the last whitespace char
    if (j == e) return j;
    if (j - 1 > p) return j - 1;
    // 6: \s+
    return j;
}

// Split every segment: matches become their own segments, and so do the gaps between them.
using Seg = std::pair<long, long>;
template <class M>
std::vector<Seg> split(const Cps &s, const std::vector<Seg> &segs, M match) {
    std::vector<Seg> out;
    for (auto [b, e] : segs) {
        long gap = b, p = b;
        while (p < e) {
            long m = match(s, p, e);
            if (m > p) {
                if (gap < p) out.push_back({gap, p});
                out.push_back({p, m});
                p = gap = m;
            } else {
                p++;
            }
        }
        if (gap < e) out.push_back({gap, e});
    }
    return out;
}

}  // namespace

// ---------------------------------------------------------------- Tokenizer

Tokenizer::Tokenizer(const GGUF &g) {
    const KV *toks = g.get("tokenizer.ggml.tokens");
    const KV *merges = g.get("tokenizer.ggml.merges");
    const KV *types = g.get("tokenizer.ggml.token_type");
    if (!toks || !merges) throw std::runtime_error("tokenizer: missing tokens or merges");
    if (g.get_str("tokenizer.ggml.model") != "gpt2") throw std::runtime_error("tokenizer: expected gpt2 BPE");

    id_to_tok_ = toks->strs;
    for (int32_t i = 0; i < int32_t(id_to_tok_.size()); i++) tok_to_id_[id_to_tok_[i]] = i;

    // GPT-2 byte <-> printable codepoint mapping.
    std::vector<int> bs;
    for (int b = '!'; b <= '~'; b++) bs.push_back(b);
    for (int b = 0xA1; b <= 0xAC; b++) bs.push_back(b);
    for (int b = 0xAE; b <= 0xFF; b++) bs.push_back(b);
    uint32_t cp_of[256];
    std::vector<bool> direct(256, false);
    for (int b : bs) direct[b] = true, cp_of[b] = uint32_t(b);
    for (int b = 0, k = 0; b < 256; b++)
        if (!direct[b]) cp_of[b] = 256 + k++;
    for (int b = 0; b < 256; b++) {
        std::string u;
        utf8_append(u, cp_of[b]);
        auto it = tok_to_id_.find(u);
        if (it == tok_to_id_.end()) throw std::runtime_error("tokenizer: missing byte token");
        byte_tok_[b] = it->second;
        cp_to_byte_[cp_of[b]] = uint8_t(b);
    }

    for (int32_t r = 0; r < int32_t(merges->strs.size()); r++) {
        const std::string &m = merges->strs[r];
        size_t sp = m.find(' ', 1);
        if (sp == std::string::npos) continue;
        std::string a = m.substr(0, sp), b = m.substr(sp + 1);
        auto ia = tok_to_id_.find(a), ib = tok_to_id_.find(b), im = tok_to_id_.find(a + b);
        if (ia == tok_to_id_.end() || ib == tok_to_id_.end() || im == tok_to_id_.end()) continue;
        merges_[(uint64_t(uint32_t(ia->second)) << 32) | uint32_t(ib->second)] = {r, im->second};
    }

    // Token types: 1 normal, 3 control, 4 user-defined. Control and user-defined tokens are added
    // tokens matched verbatim in the input (<|user|>, <think>, ...).
    if (types) {
        const int32_t *tt = reinterpret_cast<const int32_t *>(types->arr_data);
        for (int32_t i = 0; i < int32_t(types->arr_n); i++) {
            int32_t t;
            std::memcpy(&t, tt + i, 4);
            if (t == 3 || t == 4) added_.push_back({id_to_tok_[i], i});
            if (t == 3) special_.insert(i);
        }
    }
    std::sort(added_.begin(), added_.end(), [](auto &a, auto &b) { return a.first.size() > b.first.size(); });

    if (const KV *eog = g.get("tokenizer.ggml.eog_token_ids")) {
        for (uint64_t i = 0; i < eog->arr_n; i++) {
            int32_t v;
            std::memcpy(&v, eog->arr_data + 4 * i, 4);
            eog_.insert(v);
        }
    }
    eog_.insert(int32_t(g.get_int("tokenizer.ggml.eos_token_id", -1)));
}

int32_t Tokenizer::token_id(const std::string &s) const {
    auto it = tok_to_id_.find(s);
    return it == tok_to_id_.end() ? -1 : it->second;
}

std::vector<std::string> Tokenizer::pretokenize(const std::string &text) const {
    Cps s = utf8_decode(text);
    std::vector<Seg> segs{{0, long(s.size())}};
    segs = split(s, segs, match_digits);
    segs = split(s, segs, match_cjk);
    segs = split(s, segs, match_main);
    std::vector<std::string> out;
    for (auto [b, e] : segs) {
        std::string piece;
        for (long i = b; i < e; i++) utf8_append(piece, s[i]);
        out.push_back(std::move(piece));
    }
    return out;
}

void Tokenizer::bpe(const std::string &piece, std::vector<int32_t> &out) const {
    auto it = cache_.find(piece);
    if (it != cache_.end()) {
        out.insert(out.end(), it->second.begin(), it->second.end());
        return;
    }
    std::vector<int32_t> sym;
    sym.reserve(piece.size());
    for (unsigned char c : piece) sym.push_back(byte_tok_[c]);
    while (sym.size() > 1) {
        int32_t best_rank = INT32_MAX, best_id = -1;
        size_t best_i = 0;
        for (size_t i = 0; i + 1 < sym.size(); i++) {
            auto m = merges_.find((uint64_t(uint32_t(sym[i])) << 32) | uint32_t(sym[i + 1]));
            if (m != merges_.end() && m->second.first < best_rank) {
                best_rank = m->second.first;
                best_id = m->second.second;
                best_i = i;
            }
        }
        if (best_id < 0) break;
        sym[best_i] = best_id;
        sym.erase(sym.begin() + long(best_i) + 1);
    }
    if (cache_.size() < 200000) cache_[piece] = sym;
    out.insert(out.end(), sym.begin(), sym.end());
}

std::vector<int32_t> Tokenizer::encode(const std::string &text, bool parse_special) const {
    std::vector<int32_t> out;
    size_t start = 0, i = 0;
    auto flush = [&](size_t end) {
        if (end > start)
            for (auto &piece : pretokenize(text.substr(start, end - start))) bpe(piece, out);
    };
    while (parse_special && i < text.size()) {
        bool hit = false;
        if (text[i] == '<') {
            for (auto &[s, id] : added_) {
                if (text.compare(i, s.size(), s) == 0) {
                    flush(i);
                    out.push_back(id);
                    i += s.size();
                    start = i;
                    hit = true;
                    break;
                }
            }
        }
        if (!hit) i++;
    }
    flush(text.size());
    return out;
}

std::string Tokenizer::decode(int32_t id) const {
    if (id < 0 || id >= n_vocab()) return "";
    const std::string &t = id_to_tok_[id];
    if (special_.count(id)) return t;
    std::string out;
    for (uint32_t cp : utf8_decode(t)) {
        auto it = cp_to_byte_.find(cp);
        if (it != cp_to_byte_.end()) out += char(it->second);
        else utf8_append(out, cp);  // added tokens like <think> are stored as plain text
    }
    return out;
}

std::string Tokenizer::decode(const std::vector<int32_t> &ids) const {
    std::string s;
    for (int32_t id : ids) s += decode(id);
    return s;
}

}  // namespace fl
