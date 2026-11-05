// Weight formats Flint ships in, plus the 8-bit activation format the dot kernels consume.
// Block layouts match ggml so GGUF tensors are used in place, with no conversion step.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace fl {

enum : uint32_t { T_F32 = 0, T_F16 = 1, T_Q6_K = 14, T_IQ3_XXS = 18, T_IQ2_S = 22, T_BF16 = 30 };
constexpr int QK_K = 256;

#pragma pack(push, 1)
struct block_q6_K {
    uint8_t ql[QK_K / 2];      // low 4 bits
    uint8_t qh[QK_K / 4];      // high 2 bits
    int8_t scales[QK_K / 16];  // one scale per 16 weights
    uint16_t d;                // fp16 super-scale
};
struct block_iq2_s {
    uint16_t d;
    uint8_t qs[QK_K / 4];  // 32 grid indices (low 8 bits) then 32 sign bytes
    uint8_t qh[QK_K / 32];  // grid index high bits
    uint8_t scales[QK_K / 32];
};
struct block_iq3_xxs {
    uint16_t d;
    uint8_t qs[3 * QK_K / 8];  // 64 grid indices, then 8 x (4 sign indices + 4-bit scale)
};
#pragma pack(pop)

// Activations quantized per 256 values: x ~= d * qs. bsums are sums over groups of 16.
struct block_q8_K {
    float d;
    int8_t qs[QK_K];
    int16_t bsums[QK_K / 16];
};

static_assert(sizeof(block_q6_K) == 210, "q6_K layout");
static_assert(sizeof(block_iq2_s) == 82, "iq2_s layout");
static_assert(sizeof(block_iq3_xxs) == 98, "iq3_xxs layout");
static_assert(sizeof(block_q8_K) == 292, "q8_K layout");

float f16_to_f32(uint16_t h);
inline float bf16_to_f32(uint16_t h) {
    uint32_t u = uint32_t(h) << 16;
    float f;
    std::memcpy(&f, &u, 4);
    return f;
}

bool type_supported(uint32_t type);
bool type_uses_q8(uint32_t type);  // true when the dot kernel wants q8_K activations
size_t row_size(uint32_t type, int64_t n);

void dequant_row(uint32_t type, const void *src, float *dst, int64_t n);
void quantize_row_q8_K(const float *x, block_q8_K *y, int64_t n);

// Dot product of one weight row with the activation vector. Pass q8 for quantized types
// (see type_uses_q8) and xf for float types.
float vec_dot(uint32_t type, const void *row, const block_q8_K *q8, const float *xf, int64_t n);

// The AVX2 kernels, kept for machines without AVX-512 and for cross-checking.
float vec_dot_avx2(uint32_t type, const void *row, const block_q8_K *q8, int64_t n);

// Slow scalar reference: dequantize the row, dequantize the activations, dot in float.
float vec_dot_ref(uint32_t type, const void *row, const block_q8_K *q8, const float *xf, int64_t n);

}  // namespace fl
