/*
 * Bitboardy i ataki figur.
 *
 * Ataki gońców i wież liczymy „magicznymi bitboardami”: zbiór blokujących
 * figur na linii ataku mnożymy przez magiczną liczbę i bierzemy najwyższe
 * bity jako indeks do tablicy gotowych ataków. Magiczne liczby wyszukujemy
 * przy starcie (losowanie z ustalonym ziarnem, kilkanaście milisekund).
 */
#include "tm.h"

#include <string.h>

Bitboard PAWN_ATT[2][64];
Bitboard KNIGHT_ATT[64];
Bitboard KING_ATT[64];
Bitboard BETWEEN[64][64];
Bitboard LINE[64][64];

typedef struct {
    Bitboard mask;
    Bitboard magic;
    Bitboard *attacks;
    int shift;
} Magic;

static Magic BISHOP_M[64], ROOK_M[64];
static Bitboard BISHOP_TABLE[0x1480];
static Bitboard ROOK_TABLE[0x19000];

static const int ROOK_DIRS[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
static const int BISHOP_DIRS[4][2] = {{1, 1}, {1, -1}, {-1, 1}, {-1, -1}};

static Bitboard slide(int sq, Bitboard occ, const int dirs[4][2]) {
    Bitboard result = 0;
    for (int d = 0; d < 4; d++) {
        int f = FILE_OF(sq) + dirs[d][0], r = RANK_OF(sq) + dirs[d][1];
        while (f >= 0 && f < 8 && r >= 0 && r < 8) {
            int s = r * 8 + f;
            result |= BB(s);
            if (occ & BB(s)) break;
            f += dirs[d][0];
            r += dirs[d][1];
        }
    }
    return result;
}

static uint64_t rng_state = 0x9E3779B97F4A7C15ULL;
static uint64_t rng(void) {
    /* xorshift64* */
    rng_state ^= rng_state >> 12;
    rng_state ^= rng_state << 25;
    rng_state ^= rng_state >> 27;
    return rng_state * 2685821657736338717ULL;
}

static void init_magics(Magic *table, Bitboard *storage, const int dirs[4][2]) {
    static Bitboard occs[4096], atts[4096];
    static int epoch[4096];
    int cur_epoch = 0;
    Bitboard *next = storage;
    for (int sq = 0; sq < 64; sq++) {
        Bitboard edges = ((0xFFULL | 0xFF00000000000000ULL) & ~(0xFFULL << (RANK_OF(sq) * 8))) |
                         ((0x0101010101010101ULL | 0x8080808080808080ULL) & ~(0x0101010101010101ULL << FILE_OF(sq)));
        Magic *m = &table[sq];
        m->mask = slide(sq, 0, dirs) & ~edges;
        int bits = popcount(m->mask);
        m->shift = 64 - bits;
        m->attacks = next;
        int size = 0;
        Bitboard b = 0;
        do { /* wszystkie podzbiory maski (sztuczka Carry-Rippler) */
            occs[size] = b;
            atts[size] = slide(sq, b, dirs);
            size++;
            b = (b - m->mask) & m->mask;
        } while (b);
        static Bitboard used[4096];
        for (;;) {
            Bitboard magic;
            do {
                magic = rng() & rng() & rng();
            } while (popcount((m->mask * magic) >> 56) < 6);
            cur_epoch++;
            int ok = 1;
            for (int i = 0; i < size && ok; i++) {
                unsigned idx = (unsigned)((occs[i] * magic) >> m->shift);
                if (epoch[idx] < cur_epoch) {
                    epoch[idx] = cur_epoch;
                    used[idx] = atts[i];
                } else if (used[idx] != atts[i]) {
                    ok = 0;
                }
            }
            if (ok) {
                m->magic = magic;
                for (int i = 0; i < size; i++) m->attacks[(occs[i] * magic) >> m->shift] = atts[i];
                break;
            }
        }
        next += (size_t)1 << bits;
    }
}

Bitboard bishop_attacks(int sq, Bitboard occ) {
    const Magic *m = &BISHOP_M[sq];
    return m->attacks[((occ & m->mask) * m->magic) >> m->shift];
}

Bitboard rook_attacks(int sq, Bitboard occ) {
    const Magic *m = &ROOK_M[sq];
    return m->attacks[((occ & m->mask) * m->magic) >> m->shift];
}

void bb_init(void) {
    static int done = 0;
    if (done) return;
    for (int sq = 0; sq < 64; sq++) {
        int f = FILE_OF(sq), r = RANK_OF(sq);
        static const int kn[8][2] = {{1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}};
        KNIGHT_ATT[sq] = KING_ATT[sq] = 0;
        for (int i = 0; i < 8; i++) {
            int nf = f + kn[i][0], nr = r + kn[i][1];
            if (nf >= 0 && nf < 8 && nr >= 0 && nr < 8) KNIGHT_ATT[sq] |= BB(nr * 8 + nf);
        }
        for (int df = -1; df <= 1; df++)
            for (int dr = -1; dr <= 1; dr++) {
                int nf = f + df, nr = r + dr;
                if ((df || dr) && nf >= 0 && nf < 8 && nr >= 0 && nr < 8) KING_ATT[sq] |= BB(nr * 8 + nf);
            }
        PAWN_ATT[WHITE][sq] = PAWN_ATT[BLACK][sq] = 0;
        if (r < 7) {
            if (f > 0) PAWN_ATT[WHITE][sq] |= BB(sq + 7);
            if (f < 7) PAWN_ATT[WHITE][sq] |= BB(sq + 9);
        }
        if (r > 0) {
            if (f > 0) PAWN_ATT[BLACK][sq] |= BB(sq - 9);
            if (f < 7) PAWN_ATT[BLACK][sq] |= BB(sq - 7);
        }
    }
    init_magics(BISHOP_M, BISHOP_TABLE, BISHOP_DIRS);
    init_magics(ROOK_M, ROOK_TABLE, ROOK_DIRS);

    memset(BETWEEN, 0, sizeof BETWEEN);
    memset(LINE, 0, sizeof LINE);
    for (int a = 0; a < 64; a++)
        for (int b = 0; b < 64; b++) {
            if (a == b) continue;
            if (bishop_attacks(a, 0) & BB(b)) {
                BETWEEN[a][b] = bishop_attacks(a, BB(b)) & bishop_attacks(b, BB(a));
                LINE[a][b] = (bishop_attacks(a, 0) & bishop_attacks(b, 0)) | BB(a) | BB(b);
            } else if (rook_attacks(a, 0) & BB(b)) {
                BETWEEN[a][b] = rook_attacks(a, BB(b)) & rook_attacks(b, BB(a));
                LINE[a][b] = (rook_attacks(a, 0) & rook_attacks(b, 0)) | BB(a) | BB(b);
            }
        }
    done = 1;
}
