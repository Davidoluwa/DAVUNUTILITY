#include "quants.h"

#include <immintrin.h>

#include <cmath>
#include <vector>

#include "tables.h"

namespace fl {

float f16_to_f32(uint16_t h) { return _cvtsh_ss(h); }

bool type_supported(uint32_t t) {
    return t == T_F32 || t == T_F16 || t == T_BF16 || t == T_Q6_K || t == T_IQ2_S || t == T_IQ3_XXS;
}
bool type_uses_q8(uint32_t t) { return t == T_Q6_K || t == T_IQ2_S || t == T_IQ3_XXS; }

size_t row_size(uint32_t t, int64_t n) {
    switch (t) {
        case T_F32: return size_t(n) * 4;
        case T_F16: case T_BF16: return size_t(n) * 2;
        case T_Q6_K: return size_t(n / QK_K) * sizeof(block_q6_K);
        case T_IQ2_S: return size_t(n / QK_K) * sizeof(block_iq2_s);
        case T_IQ3_XXS: return size_t(n / QK_K) * sizeof(block_iq3_xxs);
        default: return 0;
    }
}

// ---------------------------------------------------------------- dequantization (reference)

static void dequant_q6_K(const block_q6_K *x, float *y, int64_t n) {
    for (int64_t i = 0; i < n / QK_K; i++) {
        const float d = f16_to_f32(x[i].d);
        const uint8_t *ql = x[i].ql, *qh = x[i].qh;
        const int8_t *sc = x[i].scales;
        for (int h = 0; h < QK_K; h += 128) {
            for (int l = 0; l < 32; ++l) {
                int is = l / 16;
                int q1 = ((ql[l] & 0xF) | (((qh[l] >> 0) & 3) << 4)) - 32;
                int q2 = ((ql[l + 32] & 0xF) | (((qh[l] >> 2) & 3) << 4)) - 32;
                int q3 = ((ql[l] >> 4) | (((qh[l] >> 4) & 3) << 4)) - 32;
                int q4 = ((ql[l + 32] >> 4) | (((qh[l] >> 6) & 3) << 4)) - 32;
                y[l + 0] = d * sc[is + 0] * q1;
                y[l + 32] = d * sc[is + 2] * q2;
                y[l + 64] = d * sc[is + 4] * q3;
                y[l + 96] = d * sc[is + 6] * q4;
            }
            y += 128;
            ql += 64;
            qh += 32;
            sc += 8;
        }
    }
}

static void dequant_iq2_s(const block_iq2_s *x, float *y, int64_t n) {
    for (int64_t i = 0; i < n / QK_K; i++) {
        const float d = f16_to_f32(x[i].d);
        const uint8_t *qs = x[i].qs, *qh = x[i].qh;
        const uint8_t *signs = qs + QK_K / 8;
        for (int ib32 = 0; ib32 < QK_K / 32; ++ib32) {
            float db[2] = {d * (0.5f + (x[i].scales[ib32] & 0xf)) * 0.25f, d * (0.5f + (x[i].scales[ib32] >> 4)) * 0.25f};
            for (int l = 0; l < 4; ++l) {
                const float dl = db[l / 2];
                const uint8_t *grid = (const uint8_t *)(iq2s_grid + (qs[l] | ((qh[ib32] << (8 - 2 * l)) & 0x300)));
                for (int j = 0; j < 8; ++j) y[j] = dl * grid[j] * ((signs[l] & kmask_iq2xs[j]) ? -1.f : 1.f);
                y += 8;
            }
            qs += 4;
            signs += 4;
        }
    }
}

static void dequant_iq3_xxs(const block_iq3_xxs *x, float *y, int64_t n) {
    for (int64_t i = 0; i < n / QK_K; i++) {
        const float d = f16_to_f32(x[i].d);
        const uint8_t *qs = x[i].qs;
        const uint8_t *sas = qs + QK_K / 4;
        for (int ib32 = 0; ib32 < QK_K / 32; ++ib32) {
            uint32_t aux;
            std::memcpy(&aux, sas + 4 * ib32, 4);
            const float db = d * (0.5f + (aux >> 28)) * 0.5f;
            for (int l = 0; l < 4; ++l) {
                const uint8_t signs = ksigns_iq2xs[(aux >> 7 * l) & 127];
                const uint8_t *g1 = (const uint8_t *)(iq3xxs_grid + qs[2 * l + 0]);
                const uint8_t *g2 = (const uint8_t *)(iq3xxs_grid + qs[2 * l + 1]);
                for (int j = 0; j < 4; ++j) {
                    y[j + 0] = db * g1[j] * ((signs & kmask_iq2xs[j + 0]) ? -1.f : 1.f);
                    y[j + 4] = db * g2[j] * ((signs & kmask_iq2xs[j + 4]) ? -1.f : 1.f);
                }
                y += 8;
            }
            qs += 8;
        }
    }
}

void dequant_row(uint32_t t, const void *src, float *dst, int64_t n) {
    switch (t) {
        case T_F32: std::memcpy(dst, src, size_t(n) * 4); break;
        case T_F16: for (int64_t i = 0; i < n; i++) dst[i] = f16_to_f32(((const uint16_t *)src)[i]); break;
        case T_BF16: for (int64_t i = 0; i < n; i++) dst[i] = bf16_to_f32(((const uint16_t *)src)[i]); break;
        case T_Q6_K: dequant_q6_K((const block_q6_K *)src, dst, n); break;
        case T_IQ2_S: dequant_iq2_s((const block_iq2_s *)src, dst, n); break;
        case T_IQ3_XXS: dequant_iq3_xxs((const block_iq3_xxs *)src, dst, n); break;
        default: break;
    }
}

// ---------------------------------------------------------------- activation quantization

void quantize_row_q8_K(const float *x, block_q8_K *y, int64_t n) {
    for (int64_t i = 0; i < n / QK_K; i++, x += QK_K) {
        float amax = 0;
        for (int j = 0; j < QK_K; j++) amax = std::fmax(amax, std::fabs(x[j]));
        if (amax == 0) {
            std::memset(&y[i], 0, sizeof(block_q8_K));
            continue;
        }
        const float id = 127.f / amax;
        for (int j = 0; j < QK_K; j++) y[i].qs[j] = int8_t(std::lrintf(x[j] * id));
        for (int g = 0; g < QK_K / 16; g++) {
            int s = 0;
            for (int j = 0; j < 16; j++) s += y[i].qs[g * 16 + j];
            y[i].bsums[g] = int16_t(s);
        }
        y[i].d = amax / 127.f;
    }
}

// ---------------------------------------------------------------- dot kernels (AVX2 integer)

static inline int hsum_i32(__m256i v) {
    __m128i s = _mm_add_epi32(_mm256_castsi256_si128(v), _mm256_extracti128_si256(v, 1));
    s = _mm_add_epi32(s, _mm_shuffle_epi32(s, 0x4e));
    s = _mm_add_epi32(s, _mm_shuffle_epi32(s, 0xb1));
    return _mm_cvtsi128_si32(s);
}

// Expand 4 sign bytes (one per group of 8 weights) to a 32-lane 0x00/0xFF mask.
static inline __m256i sign_mask(uint32_t s4) {
    const __m256i shuf = _mm256_setr_epi8(0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3,
                                          3, 3, 3, 3, 3, 3);
    const __m256i bits = _mm256_set1_epi64x(0x8040201008040201LL);
    __m256i v = _mm256_shuffle_epi8(_mm256_set1_epi32(int(s4)), shuf);
    return _mm256_cmpeq_epi8(_mm256_and_si256(v, bits), bits);
}
static inline __m256i apply_sign(__m256i q8, __m256i mask) { return _mm256_sub_epi8(_mm256_xor_si256(q8, mask), mask); }

static float dot_q6_K(const block_q6_K *x, const block_q8_K *y, int nb) {
    const __m256i m4 = _mm256_set1_epi8(0xF), m2 = _mm256_set1_epi8(3);
    float sumf = 0;
    for (int i = 0; i < nb; i++) {
        const uint8_t *ql = x[i].ql, *qh = x[i].qh;
        const int8_t *sc = x[i].scales, *q8 = y[i].qs;
        // (q - 32) * x: subtract the offset once per 16-group using precomputed activation sums.
        const __m256i sc16 = _mm256_cvtepi8_epi16(_mm_loadu_si128((const __m128i *)sc));
        const int off = hsum_i32(_mm256_madd_epi16(sc16, _mm256_loadu_si256((const __m256i *)y[i].bsums)));
        __m256i acc = _mm256_setzero_si256();
        for (int h = 0; h < 2; h++) {
            const __m256i a = _mm256_loadu_si256((const __m256i *)ql);
            const __m256i b = _mm256_loadu_si256((const __m256i *)(ql + 32));
            const __m256i hb = _mm256_loadu_si256((const __m256i *)qh);
            __m256i q[4];
            q[0] = _mm256_or_si256(_mm256_and_si256(a, m4), _mm256_slli_epi16(_mm256_and_si256(hb, m2), 4));
            q[1] = _mm256_or_si256(_mm256_and_si256(b, m4),
                                   _mm256_slli_epi16(_mm256_and_si256(_mm256_srli_epi16(hb, 2), m2), 4));
            q[2] = _mm256_or_si256(_mm256_and_si256(_mm256_srli_epi16(a, 4), m4),
                                   _mm256_slli_epi16(_mm256_and_si256(_mm256_srli_epi16(hb, 4), m2), 4));
            q[3] = _mm256_or_si256(_mm256_and_si256(_mm256_srli_epi16(b, 4), m4),
                                   _mm256_slli_epi16(_mm256_and_si256(_mm256_srli_epi16(hb, 6), m2), 4));
            for (int k = 0; k < 4; k++) {
                const __m256i p = _mm256_maddubs_epi16(q[k], _mm256_loadu_si256((const __m256i *)(q8 + 32 * k)));
                const __m256i s = _mm256_set_m128i(_mm_set1_epi16(sc[2 * k + 1]), _mm_set1_epi16(sc[2 * k]));
                acc = _mm256_add_epi32(acc, _mm256_madd_epi16(p, s));
            }
            ql += 64;
            qh += 32;
            sc += 8;
            q8 += 128;
        }
        sumf += f16_to_f32(x[i].d) * y[i].d * float(hsum_i32(acc) - 32 * off);
    }
    return sumf;
}

static float dot_iq2_s(const block_iq2_s *x, const block_q8_K *y, int nb) {
    float sumf = 0;
    for (int i = 0; i < nb; i++) {
        const uint8_t *qs = x[i].qs, *qh = x[i].qh, *signs = x[i].qs + QK_K / 8;
        const int8_t *q8 = y[i].qs;
        __m256i acc = _mm256_setzero_si256();
        for (int ib32 = 0; ib32 < QK_K / 32; ib32++) {
            const uint32_t h = qh[ib32];
            const __m256i grid = _mm256_set_epi64x(
                (long long)iq2s_grid[qs[3] | ((h << 2) & 0x300)], (long long)iq2s_grid[qs[2] | ((h << 4) & 0x300)],
                (long long)iq2s_grid[qs[1] | ((h << 6) & 0x300)], (long long)iq2s_grid[qs[0] | ((h << 8) & 0x300)]);
            uint32_t s4;
            std::memcpy(&s4, signs, 4);
            const __m256i q8s = apply_sign(_mm256_loadu_si256((const __m256i *)q8), sign_mask(s4));
            const __m256i p = _mm256_maddubs_epi16(grid, q8s);
            const int16_t ls1 = int16_t(2 * (x[i].scales[ib32] & 0xf) + 1), ls2 = int16_t(2 * (x[i].scales[ib32] >> 4) + 1);
            acc = _mm256_add_epi32(acc, _mm256_madd_epi16(p, _mm256_set_m128i(_mm_set1_epi16(ls2), _mm_set1_epi16(ls1))));
            qs += 4;
            signs += 4;
            q8 += 32;
        }
        sumf += f16_to_f32(x[i].d) * y[i].d * 0.125f * float(hsum_i32(acc));
    }
    return sumf;
}

static float dot_iq3_xxs(const block_iq3_xxs *x, const block_q8_K *y, int nb) {
    float sumf = 0;
    for (int i = 0; i < nb; i++) {
        const uint8_t *qs = x[i].qs, *sas = x[i].qs + QK_K / 4;
        const int8_t *q8 = y[i].qs;
        __m256i acc = _mm256_setzero_si256();
        for (int ib32 = 0; ib32 < QK_K / 32; ib32++) {
            uint32_t aux;
            std::memcpy(&aux, sas + 4 * ib32, 4);
            const __m256i grid = _mm256_set_epi32(int(iq3xxs_grid[qs[7]]), int(iq3xxs_grid[qs[6]]), int(iq3xxs_grid[qs[5]]),
                                                  int(iq3xxs_grid[qs[4]]), int(iq3xxs_grid[qs[3]]), int(iq3xxs_grid[qs[2]]),
                                                  int(iq3xxs_grid[qs[1]]), int(iq3xxs_grid[qs[0]]));
            const uint32_t s4 = uint32_t(ksigns_iq2xs[aux & 127]) | uint32_t(ksigns_iq2xs[(aux >> 7) & 127]) << 8 |
                                uint32_t(ksigns_iq2xs[(aux >> 14) & 127]) << 16 | uint32_t(ksigns_iq2xs[(aux >> 21) & 127]) << 24;
            const __m256i q8s = apply_sign(_mm256_loadu_si256((const __m256i *)q8), sign_mask(s4));
            const __m256i p = _mm256_maddubs_epi16(grid, q8s);
            acc = _mm256_add_epi32(acc, _mm256_madd_epi16(p, _mm256_set1_epi16(int16_t(2 * (aux >> 28) + 1))));
            qs += 8;
            q8 += 32;
        }
        sumf += f16_to_f32(x[i].d) * y[i].d * 0.25f * float(hsum_i32(acc));
    }
    return sumf;
}

// ---------------------------------------------------------------- dot kernels (AVX-512 BW + VNNI)
// Same math as the AVX2 kernels, 64 weights per step. Integer partial sums stay per block,
// then one float FMA per block; a single horizontal sum per row.
#if defined(__AVX512BW__) && defined(__AVX512VNNI__)
#define FL_AVX512 1

// Lane selectors for _mm512_permutexvar_epi16, built at compile time: 64 weights map to 32
// int16 lanes, and 8 consecutive lanes share one scale.
struct LaneIdx {
    alignas(64) int16_t v[4][32];
};
static constexpr LaneIdx make_lane_idx() {
    LaneIdx t{};
    for (int k = 0; k < 4; k++)
        for (int m = 0; m < 32; m++) t.v[k][m] = int16_t(4 * k + m / 8);
    return t;
}
static constexpr LaneIdx kLaneIdx = make_lane_idx();  // row 0 doubles as the iq2_s selector

static float dot_q6_K_512(const block_q6_K *x, const block_q8_K *y, int nb) {
    const __m512i m4 = _mm512_set1_epi8(0xF), m3 = _mm512_set1_epi8(3);
    const __m512i sh01 = _mm512_set_epi64(2, 2, 2, 2, 0, 0, 0, 0);  // high bits for elements 0-31 | 32-63
    const __m512i sh23 = _mm512_set_epi64(6, 6, 6, 6, 4, 4, 4, 4);  // ... for 64-95 | 96-127
    const __m512i sidx[4] = {_mm512_load_si512(kLaneIdx.v[0]), _mm512_load_si512(kLaneIdx.v[1]),
                             _mm512_load_si512(kLaneIdx.v[2]), _mm512_load_si512(kLaneIdx.v[3])};
    __m512 facc = _mm512_setzero_ps();
    __m256 foff = _mm256_setzero_ps();
    for (int i = 0; i < nb; i++) {
        const float d = f16_to_f32(x[i].d) * y[i].d;
        const __m256i sc16 = _mm256_cvtepi8_epi16(_mm_loadu_si128((const __m128i *)x[i].scales));
        const __m512i sc512 = _mm512_castsi256_si512(sc16);
        const __m256i off = _mm256_madd_epi16(sc16, _mm256_loadu_si256((const __m256i *)y[i].bsums));
        foff = _mm256_fmadd_ps(_mm256_cvtepi32_ps(off), _mm256_set1_ps(-32.f * d), foff);
        __m512i acc = _mm512_setzero_si512();
        for (int h = 0; h < 2; h++) {
            const __m512i A = _mm512_loadu_si512(x[i].ql + 64 * h);
            const __m512i H = _mm512_broadcast_i64x4(_mm256_loadu_si256((const __m256i *)(x[i].qh + 32 * h)));
            const __m512i hi01 = _mm512_slli_epi16(_mm512_and_si512(_mm512_srlv_epi64(H, sh01), m3), 4);
            const __m512i hi23 = _mm512_slli_epi16(_mm512_and_si512(_mm512_srlv_epi64(H, sh23), m3), 4);
            const __m512i qlo = _mm512_or_si512(_mm512_and_si512(A, m4), hi01);
            const __m512i qhi = _mm512_or_si512(_mm512_and_si512(_mm512_srli_epi16(A, 4), m4), hi23);
            const __m512i p0 = _mm512_maddubs_epi16(qlo, _mm512_loadu_si512(y[i].qs + 128 * h));
            const __m512i p1 = _mm512_maddubs_epi16(qhi, _mm512_loadu_si512(y[i].qs + 128 * h + 64));
            acc = _mm512_dpwssd_epi32(acc, p0, _mm512_permutexvar_epi16(sidx[2 * h], sc512));
            acc = _mm512_dpwssd_epi32(acc, p1, _mm512_permutexvar_epi16(sidx[2 * h + 1], sc512));
        }
        facc = _mm512_fmadd_ps(_mm512_cvtepi32_ps(acc), _mm512_set1_ps(d), facc);
    }
    return _mm512_reduce_add_ps(facc) + _mm512_reduce_add_ps(_mm512_castps256_ps512(foff));
}

static float dot_iq2_s_512(const block_iq2_s *x, const block_q8_K *y, int nb) {
    const __m512i sidx = _mm512_load_si512(kLaneIdx.v[0]);
    const __m512i zero = _mm512_setzero_si512();
    const __m256i hshift = _mm256_setr_epi32(0, 2, 4, 6, 0, 2, 4, 6), three = _mm256_set1_epi32(3);
    __m512 facc = _mm512_setzero_ps();
    for (int i = 0; i < nb; i++) {
        const uint8_t *qs = x[i].qs, *qh = x[i].qh, *signs = x[i].qs + QK_K / 8;
        const int8_t *q8 = y[i].qs;
        __m512i acc = _mm512_setzero_si512();
        for (int p = 0; p < 4; p++) {  // two 32-weight sub-blocks per step
            // 10-bit grid index per 8 weights: low 8 bits from qs, 2 high bits from qh.
            const uint32_t h0 = qh[2 * p], h1 = qh[2 * p + 1];
            const __m256i hv = _mm256_set_epi32(int(h1), int(h1), int(h1), int(h1), int(h0), int(h0), int(h0), int(h0));
            const __m256i hb = _mm256_slli_epi32(_mm256_and_si256(_mm256_srlv_epi32(hv, hshift), three), 8);
            const __m256i gi = _mm256_or_si256(_mm256_cvtepu8_epi32(_mm_loadl_epi64((const __m128i *)qs)), hb);
            const __m512i grid = _mm512_i32gather_epi64(gi, (const void *)iq2s_grid, 8);
            // The 64 sign bits are already one bit per weight: use them directly as a lane mask.
            uint64_t s;
            std::memcpy(&s, signs, 8);
            const __m512i yv = _mm512_loadu_si512(q8);
            const __m512i q8s = _mm512_mask_sub_epi8(yv, __mmask64(s), zero, yv);
            const __m512i prod = _mm512_maddubs_epi16(grid, q8s);
            const uint32_t s0 = x[i].scales[2 * p], s1 = x[i].scales[2 * p + 1];
            const uint64_t ls = uint64_t(2 * (s0 & 15) + 1) | uint64_t(2 * (s0 >> 4) + 1) << 16 |
                                uint64_t(2 * (s1 & 15) + 1) << 32 | uint64_t(2 * (s1 >> 4) + 1) << 48;
            const __m512i sv = _mm512_permutexvar_epi16(sidx, _mm512_castsi128_si512(_mm_cvtsi64_si128((long long)ls)));
            acc = _mm512_dpwssd_epi32(acc, prod, sv);
            qs += 8;
            signs += 8;
            q8 += 64;
        }
        facc = _mm512_fmadd_ps(_mm512_cvtepi32_ps(acc), _mm512_set1_ps(f16_to_f32(x[i].d) * y[i].d * 0.125f), facc);
    }
    return _mm512_reduce_add_ps(facc);
}

// Four 7-bit sign indices -> four sign bytes (bit 7 = parity), same as the ksigns_iq2xs table.
static inline uint32_t iq3_signs(uint32_t aux) {
    const uint32_t v = _pdep_u32(aux, 0x7F7F7F7Fu);
    uint32_t t = v ^ (v >> 4);
    t ^= t >> 2;
    t ^= t >> 1;
    return v | ((t & 0x01010101u) << 7);
}

static float dot_iq3_xxs_512(const block_iq3_xxs *x, const block_q8_K *y, int nb) {
    const __m512i zero = _mm512_setzero_si512();
    __m512 facc = _mm512_setzero_ps();
    for (int i = 0; i < nb; i++) {
        const uint8_t *qs = x[i].qs, *sas = x[i].qs + QK_K / 4;
        const int8_t *q8 = y[i].qs;
        __m512i acc = _mm512_setzero_si512();
        for (int p = 0; p < 4; p++) {
            uint32_t a0, a1;
            std::memcpy(&a0, sas + 8 * p, 4);
            std::memcpy(&a1, sas + 8 * p + 4, 4);
            const __m512i idx = _mm512_cvtepu8_epi32(_mm_loadu_si128((const __m128i *)qs));
            const __m512i grid = _mm512_i32gather_epi32(idx, (const void *)iq3xxs_grid, 4);
            const uint64_t s = uint64_t(iq3_signs(a0)) | uint64_t(iq3_signs(a1)) << 32;
            const __m512i yv = _mm512_loadu_si512(q8);
            const __m512i q8s = _mm512_mask_sub_epi8(yv, __mmask64(s), zero, yv);
            const __m512i prod = _mm512_maddubs_epi16(grid, q8s);
            const __m512i sv = _mm512_inserti64x4(_mm512_set1_epi16(int16_t(2 * (a0 >> 28) + 1)),
                                                  _mm256_set1_epi16(int16_t(2 * (a1 >> 28) + 1)), 1);
            acc = _mm512_dpwssd_epi32(acc, prod, sv);
            qs += 16;
            q8 += 64;
        }
        facc = _mm512_fmadd_ps(_mm512_cvtepi32_ps(acc), _mm512_set1_ps(f16_to_f32(x[i].d) * y[i].d * 0.25f), facc);
    }
    return _mm512_reduce_add_ps(facc);
}
#endif

static float dot_bf16(const uint16_t *w, const float *x, int64_t n) {
    __m512 acc = _mm512_setzero_ps();
    int64_t i = 0;
    for (; i + 16 <= n; i += 16) {
        __m512i wi = _mm512_slli_epi32(_mm512_cvtepu16_epi32(_mm256_loadu_si256((const __m256i *)(w + i))), 16);
        acc = _mm512_fmadd_ps(_mm512_castsi512_ps(wi), _mm512_loadu_ps(x + i), acc);
    }
    float s = _mm512_reduce_add_ps(acc);
    for (; i < n; i++) s += bf16_to_f32(w[i]) * x[i];
    return s;
}

static float dot_f32(const float *w, const float *x, int64_t n) {
    __m512 acc = _mm512_setzero_ps();
    int64_t i = 0;
    for (; i + 16 <= n; i += 16) acc = _mm512_fmadd_ps(_mm512_loadu_ps(w + i), _mm512_loadu_ps(x + i), acc);
    float s = _mm512_reduce_add_ps(acc);
    for (; i < n; i++) s += w[i] * x[i];
    return s;
}

float vec_dot_avx2(uint32_t t, const void *row, const block_q8_K *q8, int64_t n) {
    switch (t) {
        case T_Q6_K: return dot_q6_K((const block_q6_K *)row, q8, int(n / QK_K));
        case T_IQ2_S: return dot_iq2_s((const block_iq2_s *)row, q8, int(n / QK_K));
        case T_IQ3_XXS: return dot_iq3_xxs((const block_iq3_xxs *)row, q8, int(n / QK_K));
        default: return 0;
    }
}

float vec_dot(uint32_t t, const void *row, const block_q8_K *q8, const float *xf, int64_t n) {
    switch (t) {
#ifdef FL_AVX512
        case T_Q6_K: return dot_q6_K_512((const block_q6_K *)row, q8, int(n / QK_K));
        case T_IQ2_S: return dot_iq2_s_512((const block_iq2_s *)row, q8, int(n / QK_K));
        case T_IQ3_XXS: return dot_iq3_xxs_512((const block_iq3_xxs *)row, q8, int(n / QK_K));
#else
        case T_Q6_K: case T_IQ2_S: case T_IQ3_XXS: return vec_dot_avx2(t, row, q8, n);
#endif
        case T_BF16: return dot_bf16((const uint16_t *)row, xf, n);
        case T_F32: return dot_f32((const float *)row, xf, n);
        default: return vec_dot_ref(t, row, q8, xf, n);
    }
}

float vec_dot_ref(uint32_t t, const void *row, const block_q8_K *q8, const float *xf, int64_t n) {
    std::vector<float> w(n), x(n);
    dequant_row(t, row, w.data(), n);
    if (type_uses_q8(t)) {
        for (int64_t i = 0; i < n; i++) x[i] = q8[i / QK_K].d * q8[i / QK_K].qs[i % QK_K];
    } else {
        for (int64_t i = 0; i < n; i++) x[i] = xf[i];
    }
    double s = 0;
    for (int64_t i = 0; i < n; i++) s += double(w[i]) * x[i];
    return float(s);
}

}  // namespace fl
