// Print token ids for each line of a file (escapes: \n \t \\), one line of ids per input line.
//   tokenize MODEL.gguf STRINGS.txt
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>

#include "../src/gguf.h"
#include "../src/tokenizer.h"

static std::string unescape(const std::string &s) {
    std::string o;
    for (size_t i = 0; i < s.size(); i++) {
        if (s[i] == '\\' && i + 1 < s.size()) {
            char c = s[++i];
            o += c == 'n' ? '\n' : c == 't' ? '\t' : c == 'r' ? '\r' : c;
        } else {
            o += s[i];
        }
    }
    return o;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: %s MODEL.gguf STRINGS.txt\n", argv[0]);
        return 1;
    }
    fl::GGUF g(argv[1]);
    fl::Tokenizer tok(g);
    std::ifstream in(argv[2]);
    std::string line;
    while (std::getline(in, line)) {
        auto ids = tok.encode(unescape(line), true);
        for (size_t i = 0; i < ids.size(); i++) std::printf("%s%d", i ? " " : "", ids[i]);
        std::printf("\n");
        if (tok.decode(ids) != unescape(line)) std::fprintf(stderr, "round-trip mismatch: %s\n", line.c_str());
    }
    return 0;
}
