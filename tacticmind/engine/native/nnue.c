/*
 * NNUE - "efficiently updatable neural network" for position evaluation.
 *
 * Input: 768 binary features (color x piece type x square), seen from
 * White's perspective and separately from Black's (mirrored board).
 * The first layer (768 -> 256) is shared by both perspectives. Its output,
 * the accumulator, is updated incrementally on every move (see
 * position.c), because a move changes only 2-4 features.
 *
 * Evaluation: [side-to-move accumulator, opponent accumulator] -> SCReLU
 * (clamp(x, 0, 1)^2) -> output layer 512 -> 1. There are several output
 * layers ("buckets"): one is chosen by the number of pieces on the board,
 * because in the endgame the same features mean something different than
 * in the opening. Weights are quantised to integers (QA = 255, QB = 64), so
 * all arithmetic is in int16/int32.
 *
 * File format (little-endian):
 *   "TMNN" | uint32 version = 2 | uint32 HIDDEN | uint32 BUCKETS
 *   int16 ft_w[768 * HIDDEN] | int16 ft_b[HIDDEN] | int16 out_w[BUCKETS][2 * HIDDEN] | int16 out_b[BUCKETS]
 * Version 1 (no BUCKETS field, a single output layer) is also read.
 */
#include "tm.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

Network NET;
int NET_LOADED = 0;

int nnue_feature(int persp, int piece, int sq);

static int read_i16(const unsigned char **p, const unsigned char *end, int16_t *out, size_t n) {
    if ((size_t)(end - *p) < n * 2) return 0;
    for (size_t i = 0; i < n; i++) {
        out[i] = (int16_t)((*p)[0] | ((*p)[1] << 8));
        *p += 2;
    }
    return 1;
}

int nnue_load_memory(const unsigned char *data, size_t size) {
    const unsigned char *p = data, *end = data + size;
    if (size < 12 || memcmp(p, "TMNN", 4) != 0) return 0;
    unsigned version = p[4] | (p[5] << 8) | (p[6] << 16) | ((unsigned)p[7] << 24);
    unsigned hidden = p[8] | (p[9] << 8) | (p[10] << 16) | ((unsigned)p[11] << 24);
    unsigned buckets = 1;
    p += 12;
    if (version == 2) {
        if (size < 16) return 0;
        buckets = p[0] | (p[1] << 8) | (p[2] << 16) | ((unsigned)p[3] << 24);
        p += 4;
    } else if (version != 1) {
        return 0;
    }
    if (hidden != NNUE_HIDDEN || buckets < 1 || buckets > NNUE_MAX_BUCKETS) return 0;
    static Network tmp;
    memset(&tmp, 0, sizeof tmp);
    tmp.buckets = (int)buckets;
    if (!read_i16(&p, end, tmp.ft_w, NNUE_INPUTS * NNUE_HIDDEN) || !read_i16(&p, end, tmp.ft_b, NNUE_HIDDEN))
        return 0;
    for (unsigned b = 0; b < buckets; b++)
        if (!read_i16(&p, end, tmp.out_w[b], 2 * NNUE_HIDDEN)) return 0;
    if (!read_i16(&p, end, tmp.out_b, buckets) || p != end) return 0;
    NET = tmp;
    NET_LOADED = 1;
    return 1;
}

int nnue_load(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size <= 0) {
        fclose(f);
        return 0;
    }
    unsigned char *buf = malloc((size_t)size);
    int ok = buf && fread(buf, 1, (size_t)size, f) == (size_t)size && nnue_load_memory(buf, (size_t)size);
    free(buf);
    fclose(f);
    return ok;
}

void nnue_refresh(const Position *pos, Accumulator *acc) {
    for (int persp = 0; persp < 2; persp++) {
        int16_t *v = acc->v[persp];
        memcpy(v, NET.ft_b, sizeof(int16_t) * NNUE_HIDDEN);
        for (int sq = 0; sq < 64; sq++) {
            int pc = pos->board[sq];
            if (pc == NO_PIECE) continue;
            const int16_t *w = &NET.ft_w[nnue_feature(persp, pc, sq) * NNUE_HIDDEN];
            for (int i = 0; i < NNUE_HIDDEN; i++) v[i] += w[i];
        }
    }
}

/* dst = src + sum of columns(add) - sum of columns(sub); add/sub = piece*64 + square. */
void nnue_update(Accumulator *dst, const Accumulator *src, const int *add, int nadd, const int *sub, int nsub) {
    for (int persp = 0; persp < 2; persp++) {
        const int16_t *a0 = &NET.ft_w[nnue_feature(persp, add[0] >> 6, add[0] & 63) * NNUE_HIDDEN];
        const int16_t *s0 = &NET.ft_w[nnue_feature(persp, sub[0] >> 6, sub[0] & 63) * NNUE_HIDDEN];
        const int16_t *in = src->v[persp];
        int16_t *out = dst->v[persp];
        if (nadd == 1 && nsub == 1) {
            for (int i = 0; i < NNUE_HIDDEN; i++) out[i] = (int16_t)(in[i] + a0[i] - s0[i]);
        } else if (nadd == 1 && nsub == 2) {
            const int16_t *s1 = &NET.ft_w[nnue_feature(persp, sub[1] >> 6, sub[1] & 63) * NNUE_HIDDEN];
            for (int i = 0; i < NNUE_HIDDEN; i++) out[i] = (int16_t)(in[i] + a0[i] - s0[i] - s1[i]);
        } else { /* castling: 2 added, 2 removed */
            const int16_t *a1 = &NET.ft_w[nnue_feature(persp, add[1] >> 6, add[1] & 63) * NNUE_HIDDEN];
            const int16_t *s1 = &NET.ft_w[nnue_feature(persp, sub[1] >> 6, sub[1] & 63) * NNUE_HIDDEN];
            for (int i = 0; i < NNUE_HIDDEN; i++) out[i] = (int16_t)(in[i] + a0[i] + a1[i] - s0[i] - s1[i]);
        }
    }
}

static inline int32_t screlu_dot(const int16_t *v, const int16_t *w) {
    int32_t sum = 0;
    for (int i = 0; i < NNUE_HIDDEN; i++) {
        int16_t x = v[i] < 0 ? 0 : v[i] > NNUE_QA ? NNUE_QA : v[i];
        /* x * w fits in int16 (|w| <= 127); only then do we multiply by x in int32. */
        sum += (int32_t)(int16_t)(x * w[i]) * x;
    }
    return sum;
}

int nnue_evaluate(const Position *pos) {
    const Accumulator *acc = &pos->acc[pos->ply];
    int us = pos->side;
    int bucket = NNUE_BUCKET(popcount(pos->occupied), NET.buckets);
    const int16_t *w = NET.out_w[bucket];
    int64_t sum = (int64_t)screlu_dot(acc->v[us], w) + screlu_dot(acc->v[us ^ 1], w + NNUE_HIDDEN);
    int64_t out = sum / NNUE_QA + NET.out_b[bucket];
    return (int)(out * NNUE_SCALE / (NNUE_QA * NNUE_QB));
}
