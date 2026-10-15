/*
 * Ocena pozycji.
 *
 * Domyślnie liczy ją sieć NNUE (nnue.c). Ręczna ocena poniżej (materiał,
 * tablice pozycyjne, mobilność, struktura pionków, para gońców, osłona króla)
 * to ta sama idea co w silniku w Pythonie. Służy jako zapas, gdy nie ma
 * pliku sieci, i jako „nauczyciel” pierwszej generacji danych treningowych.
 */
#include "tm.h"

#include <stdlib.h>

static const int MAT_MG[6] = {100, 320, 330, 500, 950, 0};
static const int MAT_EG[6] = {120, 300, 320, 540, 980, 0};
static const int PHASE_W[6] = {0, 1, 1, 2, 4, 0};

/* Tablice z perspektywy białych, wiersz 0 = 8. rząd (jak w pst.py). */
static const int PST_MG[6][64] = {
    {0, 0, 0, 0, 0, 0, 0, 0, 50, 50, 50, 50, 50, 50, 50, 50, 10, 10, 20, 30, 30, 20, 10, 10, 5, 5, 10, 25, 25, 10, 5, 5,
     0, 0, 0, 20, 20, 0, 0, 0, 5, -5, -10, 0, 0, -10, -5, 5, 5, 10, 10, -20, -20, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0},
    {-50, -40, -30, -30, -30, -30, -40, -50, -40, -20, 0, 0, 0, 0, -20, -40, -30, 0, 10, 15, 15, 10, 0, -30,
     -30, 5, 15, 20, 20, 15, 5, -30, -30, 0, 15, 20, 20, 15, 0, -30, -30, 5, 10, 15, 15, 10, 5, -30,
     -40, -20, 0, 5, 5, 0, -20, -40, -50, -40, -30, -30, -30, -30, -40, -50},
    {-20, -10, -10, -10, -10, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10, -10, 0, 5, 10, 10, 5, 0, -10,
     -10, 5, 5, 10, 10, 5, 5, -10, -10, 0, 10, 10, 10, 10, 0, -10, -10, 10, 10, 10, 10, 10, 10, -10,
     -10, 5, 0, 0, 0, 0, 5, -10, -20, -10, -10, -10, -10, -10, -10, -20},
    {0, 0, 0, 0, 0, 0, 0, 0, 5, 10, 10, 10, 10, 10, 10, 5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5,
     -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, 0, 0, 0, 5, 5, 0, 0, 0},
    {-20, -10, -10, -5, -5, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10, -10, 0, 5, 5, 5, 5, 0, -10,
     -5, 0, 5, 5, 5, 5, 0, -5, 0, 0, 5, 5, 5, 5, 0, -5, -10, 5, 5, 5, 5, 5, 0, -10,
     -10, 0, 5, 0, 0, 0, 0, -10, -20, -10, -10, -5, -5, -10, -10, -20},
    {-30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30,
     -30, -40, -40, -50, -50, -40, -40, -30, -20, -30, -30, -40, -40, -30, -30, -20, -10, -20, -20, -20, -20, -20, -20, -10,
     20, 20, 0, 0, 0, 0, 20, 20, 20, 30, 10, 0, 0, 10, 30, 20},
};
static const int PST_EG_PAWN[64] = {0, 0, 0, 0, 0, 0, 0, 0, 80, 80, 80, 80, 80, 80, 80, 80, 50, 50, 50, 50, 50, 50, 50, 50,
                                    30, 30, 30, 30, 30, 30, 30, 30, 15, 15, 15, 15, 15, 15, 15, 15, 5, 5, 5, 5, 5, 5, 5, 5,
                                    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
static const int PST_EG_ROOK[64] = {5, 5, 5, 5, 5, 5, 5, 5, 10, 10, 10, 10, 10, 10, 10, 10};
static const int PST_EG_KING[64] = {-50, -40, -30, -20, -20, -30, -40, -50, -30, -20, -10, 0, 0, -10, -20, -30,
                                    -30, -10, 20, 30, 30, 20, -10, -30, -30, -10, 30, 40, 40, 30, -10, -30,
                                    -30, -10, 30, 40, 40, 30, -10, -30, -30, -10, 20, 30, 30, 20, -10, -30,
                                    -30, -30, 0, 0, 0, 0, -30, -30, -50, -30, -30, -30, -30, -30, -30, -50};

static const int MOB_MG[6] = {0, 4, 5, 2, 1, 0};
static const int MOB_EG[6] = {0, 4, 5, 4, 2, 0};
static const int MOB_BASE[6] = {0, 4, 6, 6, 12, 0};
static const int PASSED_MG[8] = {0, 5, 10, 15, 25, 40, 60, 0};
static const int PASSED_EG[8] = {0, 10, 20, 35, 60, 95, 140, 0};

static inline int pst_index(int sq, int color) { return color == WHITE ? (7 - RANK_OF(sq)) * 8 + FILE_OF(sq) : sq; }

static const Bitboard FILE_A = 0x0101010101010101ULL;

static int king_shield(const Position *pos, int color) {
    int k = king_sq(pos, color);
    int kr = RANK_OF(k), kf = FILE_OF(k);
    int home = color == WHITE ? 0 : 7;
    if (abs(kr - home) > 1) return -20;
    Bitboard own = pos_bb(pos, color, PAWN), enemy = pos_bb(pos, color ^ 1, PAWN);
    int step = color == WHITE ? 1 : -1;
    int score = 0;
    for (int f = kf > 0 ? kf - 1 : 0; f <= (kf < 7 ? kf + 1 : 7); f++) {
        int r1 = kr + step, r2 = kr + 2 * step;
        if (r1 >= 0 && r1 < 8 && (own & BB(r1 * 8 + f)))
            score += 12;
        else if (r2 >= 0 && r2 < 8 && (own & BB(r2 * 8 + f)))
            score += 6;
        else
            score -= 12;
        if (!(own & (FILE_A << f))) score -= (enemy & (FILE_A << f)) ? 8 : 15;
    }
    return score;
}

int eval_hce(const Position *pos) {
    int mg[2] = {0, 0}, eg[2] = {0, 0}, phase = 0;
    for (int c = 0; c < 2; c++) {
        Bitboard own = pos->by_color[c];
        for (int t = PAWN; t <= KING; t++) {
            Bitboard b = pos_bb(pos, c, t);
            while (b) {
                int sq = pop_lsb(&b);
                int idx = pst_index(sq, c);
                phase += PHASE_W[t];
                mg[c] += MAT_MG[t] + PST_MG[t][idx];
                int eg_pst = t == PAWN ? PST_EG_PAWN[idx] : t == ROOK ? PST_EG_ROOK[idx] : t == KING ? PST_EG_KING[idx] : PST_MG[t][idx];
                eg[c] += MAT_EG[t] + eg_pst;
                if (t >= KNIGHT && t <= QUEEN) {
                    Bitboard att = t == KNIGHT   ? KNIGHT_ATT[sq]
                                   : t == BISHOP ? bishop_attacks(sq, pos->occupied)
                                   : t == ROOK   ? rook_attacks(sq, pos->occupied)
                                                 : queen_attacks(sq, pos->occupied);
                    int mob = popcount(att & ~own) - MOB_BASE[t];
                    mg[c] += mob * MOB_MG[t];
                    eg[c] += mob * MOB_EG[t];
                    int ek = king_sq(pos, c ^ 1);
                    int dist = abs(FILE_OF(ek) - FILE_OF(sq)) > abs(RANK_OF(ek) - RANK_OF(sq)) ? abs(FILE_OF(ek) - FILE_OF(sq))
                                                                                              : abs(RANK_OF(ek) - RANK_OF(sq));
                    static const int TROP[6] = {0, 2, 1, 2, 4, 0};
                    mg[c] += (7 - dist) * TROP[t];
                }
            }
        }
        /* Piony: zdwojone, izolowane, przechodnie. */
        Bitboard pawns = pos_bb(pos, c, PAWN), theirs = pos_bb(pos, c ^ 1, PAWN);
        for (int f = 0; f < 8; f++) {
            Bitboard on_file = pawns & (FILE_A << f);
            int n = popcount(on_file);
            if (!n) continue;
            if (n > 1) {
                mg[c] -= 10 * (n - 1);
                eg[c] -= 20 * (n - 1);
            }
            Bitboard adj = (f > 0 ? FILE_A << (f - 1) : 0) | (f < 7 ? FILE_A << (f + 1) : 0);
            if (!(pawns & adj)) {
                mg[c] -= 10 * n;
                eg[c] -= 15 * n;
            }
            int sq = c == WHITE ? 63 - __builtin_clzll(on_file) : lsb(on_file);
            int rank = RANK_OF(sq);
            Bitboard span = (FILE_A << f) | adj;
            Bitboard front = c == WHITE ? (rank < 7 ? span & (~0ULL << ((rank + 1) * 8)) : 0) : (rank > 0 ? span & ((1ULL << (rank * 8)) - 1) : 0);
            if (!(theirs & front)) {
                int rel = c == WHITE ? rank : 7 - rank;
                mg[c] += PASSED_MG[rel];
                eg[c] += PASSED_EG[rel];
            }
        }
        if (popcount(pos_bb(pos, c, BISHOP)) >= 2) {
            mg[c] += 30;
            eg[c] += 50;
        }
        mg[c] += king_shield(pos, c);
    }
    if (phase > 24) phase = 24;
    int score = ((mg[0] - mg[1]) * phase + (eg[0] - eg[1]) * (24 - phase)) / 24;
    return pos->side == WHITE ? score : -score;
}

int evaluate(Position *pos) {
    if (pos_insufficient(pos)) return 0;
    int v = (pos->use_nnue && NET_LOADED) ? nnue_evaluate(pos) : eval_hce(pos);
    /* Zbliżanie się do reguły 50 ruchów ściąga ocenę do remisu. */
    v = v * (200 - pos->halfmove) / 200;
    if (v > MATE_BOUND - 1) v = MATE_BOUND - 1;
    if (v < -MATE_BOUND + 1) v = -MATE_BOUND + 1;
    return v;
}
