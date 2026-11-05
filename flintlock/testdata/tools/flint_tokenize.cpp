// flint_tokenize: tokenize many strings with llama.cpp's tokenizer (vocab only, no weights loaded).
//
// Usage: flint_tokenize MODEL.gguf STRINGS.bin
//   STRINGS.bin: repeated [uint32 little-endian byte length][UTF-8 bytes]
//   Output: one line per string, space-separated token ids.
// Special tokens (e.g. <|user|>) are parsed; no BOS is added (Flint: add_bos_token = false).
//
// Build: g++ -O2 -std=c++17 flint_tokenize.cpp -I$LLAMA/include -I$LLAMA/ggml/include \
//        -L$LLAMA/build/bin -lllama -Wl,-rpath,$LLAMA/build/bin -o flint_tokenize
#include "llama.h"

#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

int main(int argc, char ** argv) {
    if (argc != 3) { fprintf(stderr, "usage: %s MODEL.gguf STRINGS.bin\n", argv[0]); return 1; }
    llama_backend_init();
    llama_model_params mp = llama_model_default_params();
    mp.vocab_only = true;
    llama_model * model = llama_model_load_from_file(argv[1], mp);
    if (!model) { fprintf(stderr, "load failed\n"); return 1; }
    const llama_vocab * vocab = llama_model_get_vocab(model);

    FILE * f = fopen(argv[2], "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", argv[2]); return 1; }
    uint32_t len;
    while (fread(&len, 4, 1, f) == 1) {
        std::string s(len, '\0');
        if (len && fread(&s[0], 1, len, f) != len) { fprintf(stderr, "short read\n"); return 1; }
        int n = -llama_tokenize(vocab, s.data(), (int) s.size(), nullptr, 0, false, true);
        std::vector<llama_token> toks(n > 0 ? n : 0);
        if (n > 0 && llama_tokenize(vocab, s.data(), (int) s.size(), toks.data(), n, false, true) < 0) {
            fprintf(stderr, "tokenize failed\n");
            return 1;
        }
        for (size_t i = 0; i < toks.size(); ++i) printf(i ? " %d" : "%d", toks[i]);
        printf("\n");
    }
    fclose(f);
    llama_model_free(model);
    llama_backend_free();
    return 0;
}
