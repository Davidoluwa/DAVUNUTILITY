// Byte-level BPE tokenizer for Flint, matching the original Hugging Face tokenizer.
// The pre-tokenizer keeps uppercase and lowercase letter classes distinct (camelCase splits
// at the capital), which llama.cpp does not do.
#pragma once
#include <cstdint>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "gguf.h"

namespace fl {

class Tokenizer {
public:
    explicit Tokenizer(const GGUF &g);

    // parse_special: match added tokens such as <|user|> or <think> in the raw text.
    std::vector<int32_t> encode(const std::string &text, bool parse_special = true) const;
    std::string decode(int32_t id) const;
    std::string decode(const std::vector<int32_t> &ids) const;

    // Pre-tokenizer output (the pieces BPE runs on), exposed for tests.
    std::vector<std::string> pretokenize(const std::string &text) const;

    bool is_eog(int32_t id) const { return eog_.count(id) != 0; }
    int32_t n_vocab() const { return int32_t(id_to_tok_.size()); }
    int32_t token_id(const std::string &s) const;

private:
    void bpe(const std::string &piece, std::vector<int32_t> &out) const;

    std::vector<std::string> id_to_tok_;
    std::unordered_map<std::string, int32_t> tok_to_id_;
    std::unordered_map<uint64_t, std::pair<int32_t, int32_t>> merges_;  // (left,right) -> (rank, merged)
    std::vector<std::pair<std::string, int32_t>> added_;              // longest first
    std::unordered_set<int32_t> special_;  // rendered verbatim on decode
    std::unordered_set<int32_t> eog_;
    int32_t byte_tok_[256];
    std::unordered_map<uint32_t, uint8_t> cp_to_byte_;
    mutable std::unordered_map<std::string, std::vector<int32_t>> cache_;
};

}  // namespace fl
