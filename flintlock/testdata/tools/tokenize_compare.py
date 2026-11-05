#!/usr/bin/env python3
"""Reference tokenizations for Flint from two tokenizers, and where they disagree.

Usage: python tokenize_compare.py FLINT_TOKENIZE_BIN MODEL.gguf TOKENIZER_JSON OUT.json

- llama.cpp: flint_tokenize (vocab-only load of the GGUF), special tokens parsed, no BOS.
- Hugging Face `tokenizers`: Tokenizer.from_file(RecursiveSI/flint tokenizer.json),
  encode(s, add_special_tokens=False). This is the original tokenizer and the one to match.
"""
import json
import os
import struct
import subprocess
import sys
import tempfile

from tokenizers import Tokenizer

STRINGS = [
    # --- general (the ~20 varied strings from the brief) ---
    ("plain", "Hello, world! This is a simple sentence."),
    ("py_code", "def fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\n"),
    ("c_code_tabs", "int main(void) {\n\tprintf(\"%d\\n\", 42);\n\treturn 0;\n}\n"),
    ("whitespace_runs", "a  b   c    d\n\n\n    e\t\t f        \n  \n"),
    ("leading_trailing_space", "   leading and trailing   "),
    ("numbers", "1234567890 3.14159 1e-9 0xDEADBEEF 1,000,000 -42"),
    ("latin_unicode", "Grüße aus Köln — naïve café, ½ € £ ¥ «quotes» “curly”"),
    ("cjk", "机器学习很有趣。日本語のテキストとカタカナ。한국어 텍스트"),
    ("rtl_indic_cyrillic", "مرحبا بالعالم שלום עולם नमस्ते दुनिया Привет, мир"),
    ("emoji_zwj", "😀👍🏽 👨‍👩‍👧‍👦 family, 🏳️‍🌈 flag"),
    ("combining_marks", "e\u0301 vs \u00e9, n\u0303, a\u0308\u0304"),
    ("contractions", "I'm sure you'll see they've done it, isn't it? I'D SAY WE'RE DONE"),
    ("url_path", "https://example.com/a/b?x=1&y=2#frag C:\\Users\\me\\file.txt ~/.bashrc"),
    ("json", "{\"key\": [1, 2, {\"nested\": null}], \"flag\": true, \"pi\": 3.14}"),
    ("markdown", "# Title\n\n- item one\n- **bold** and `code`\n\n| a | b |\n|---|---|\n"),
    ("chat_template", "<|system|>You are a helpful assistant.<|user|>Hi there!<|assistant|>"),
    ("chat_tools", "<|assistant|><think>Need weather.</think><tool_call>get_weather<arg_key>city</arg_key>"
                   "<arg_value>Paris</arg_value></tool_call><|observation|><tool_response>18C</tool_response>"),
    ("newline_only", "\n"),
    ("single_space", " "),
    ("repeats", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ==================== ....... !!!???"),
    ("versions", "abc123def456 v1.2.3-beta+build.5 x86_64 utf-8"),
    # --- camelCase / ALLCAPS (case-boundary splitting) ---
    ("camel_basic", "camelCase getElementById parseJsonResponse"),
    ("camel_acronyms", "XMLHttpRequest HTTPServer getHTTPResponseCode parseJSONResponse"),
    ("camel_short", "iPhone eBay McDonald's macOS"),
    ("pascal", "PascalCaseIdentifier MyVariableName2 ToString()"),
    ("allcaps_words", "ALLCAPS SHOUTING TEXT WITH NUMBERS 123ABC"),
    ("allcaps_snake", "CONSTANT_VALUE MAX_BUFFER_SIZE snake_case_name kebab-case-name"),
    ("case_mix", "fooBar fooBAR FOObar FooBar fOO FOO_bar"),
    ("allcaps_contractions", "NASA's API DOESN'T WORK, IT'S THE SERVER'S FAULT"),
    ("nonascii_case", "ÉCOLE École écoleNormale ΑΘΗΝΑ Αθήνα straßeGroß"),
    ("camel_code", "const userAccountId = await fetchUserData(requestId);\n"
                   "if (!isValid) throw new TypeError('badInput: ' + errorMsg);\n"),
    ("java_code", "public class HttpClientFactory {\n    private static final int MAX_RETRY_COUNT = 3;\n"
                  "    public HttpClient createDefaultClient() { return new HttpClient(); }\n}\n"),
    # --- non-ASCII case boundaries: upper and lower share a UTF-8 lead byte, so a byte-level
    #     merge can cross the boundary when the pre-tokenizer does not split there (found by fuzzing) ---
    ("cyrillic_camel", "ПоИД идСпрПоИД имяПользователя getИмяФайла"),
    ("cyrillic_caps", "ПРИВЕТмир приветМИР ОшибкаСети КодОшибки"),
    ("greek_camel", "τιμήΜέγιστη μέγεθοςΠίνακα ΑθήναΚέντρο"),
    ("latin1_camel", "caféÉcole naïveÜber straßeÄnderung déjàVu"),
    ("mixed_script_camel", "userИмя idΑριθμός fooÉtat dataÇount"),
]


def main():
    tok_bin, model, tok_json, out = sys.argv[1:5]
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        for _, s in STRINGS:
            b = s.encode('utf-8')
            f.write(struct.pack('<I', len(b)))
            f.write(b)
        path = f.name
    res = subprocess.run([tok_bin, model, path], capture_output=True, text=True, check=True)
    os.unlink(path)
    lines = res.stdout.split('\n')[:len(STRINGS)]
    llama_ids = [[int(x) for x in l.split()] for l in lines]

    hf = Tokenizer.from_file(tok_json)
    rows = []
    n_dis = 0
    for (name, s), lc in zip(STRINGS, llama_ids):
        enc = hf.encode(s, add_special_tokens=False)
        agree = enc.ids == lc
        n_dis += not agree
        row = {'name': name, 'text': s, 'hf_ids': enc.ids, 'llama_cpp_ids': lc, 'agree': agree}
        if not agree:
            row['hf_pieces'] = [hf.decode([i]) for i in enc.ids]
            row['llama_cpp_pieces'] = [hf.decode([i]) for i in lc]
            row['hf_pretokens'] = [p for p, _ in hf.pre_tokenizer.pre_tokenize_str(s)] if hf.pre_tokenizer else None
            # both must at least decode back to the same text
            row['llama_cpp_roundtrip_ok'] = hf.decode(lc, skip_special_tokens=False) == hf.decode(enc.ids, skip_special_tokens=False)
        rows.append(row)
    json.dump({'tokenizer_json': tok_json, 'model': model, 'n_strings': len(rows), 'n_disagree': n_dis,
               'strings': rows}, open(out, 'w'), ensure_ascii=False, indent=1)
    for r in rows:
        print(f"{'OK  ' if r['agree'] else 'DIFF'} {r['name']:24s} hf={len(r['hf_ids']):3d} llama={len(r['llama_cpp_ids']):3d}")
    print(f'{n_dis} of {len(rows)} disagree')


if __name__ == '__main__':
    main()
