/*
 * Bitboardy i ataki figur.
 *
 * Ataki gońców i wież liczymy „magicznymi bitboardami”: zbiór blokujących
 * figur na linii ataku mnożymy przez magiczną liczbę i bierzemy najwyższe
 * bity jako indeks do tablicy gotowych ataków. Magiczne liczby znaleźliśmy
 * losowaniem z ustalonym ziarnem (ten sam algorytm jest niżej) i zapisaliśmy
 * w tablicach — przy starcie tylko je sprawdzamy, co trwa ułamek milisekundy
 * zamiast ok. 0,3 s szukania.
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

/* Wynik wyszukiwania poniżej (init_magics) dla ziarna rng_state. */
static const uint64_t BISHOP_MAGICS[64] = {
    0x10102002004A1420ULL, 0x8020040400584008ULL, 0x10510800811201C8ULL, 0x5204042080000088ULL,
    0x2204106880000002ULL, 0x1401042004000000ULL, 0x0400880410042004ULL, 0x0028208200A02020ULL,
    0x1500241990010E00ULL, 0x8001200182020A40ULL, 0x40004101030B0000ULL, 0x8002041042000100ULL,
    0x4010011041020038ULL, 0x0000010421044000ULL, 0x1500210808020A00ULL, 0x8000088400880520ULL,
    0x0405004010040100ULL, 0x1005823210040108ULL, 0x2708008102040011ULL, 0x4048200404009100ULL,
    0x0018104101400024ULL, 0x0003000601190101ULL, 0x8004803108491000ULL, 0x8014241200820800ULL,
    0x0006E080100C3040ULL, 0x0501044A11041800ULL, 0x9020300008004045ULL, 0x0894080000220040ULL,
    0x1001010083104000ULL, 0x5004030040900080ULL, 0x000400422C012400ULL, 0x0002128698404812ULL,
    0x1010108404900440ULL, 0x0928021182084100ULL, 0x2006080409020024ULL, 0x1010202020180080ULL,
    0xA010008200202200ULL, 0x2098015100019004ULL, 0x0002041440810811ULL, 0x802A02020000B098ULL,
    0x0009015090004060ULL, 0x4000821082081001ULL, 0x0100210040420800ULL, 0x0800004010488A00ULL,
    0x2000081104004040ULL, 0x4C8E029015000082ULL, 0x0420340322224842ULL, 0x1298260043400210ULL,
    0x0000822802400008ULL, 0x00008A0101600000ULL, 0x3040003412080021ULL, 0x3040290220884800ULL,
    0x4A1500401041004AULL, 0x8010200282020781ULL, 0x0020203142209091ULL, 0x0070300600902110ULL,
    0x0040808800B62048ULL, 0x0000810400C44420ULL, 0x00080400440C0441ULL, 0x8340080020840411ULL,
    0x0000000104208200ULL, 0x0000800810D00080ULL, 0x0400530411080200ULL, 0x4040702400932244ULL,
};
static const uint64_t ROOK_MAGICS[64] = {
    0x1080008040001021ULL, 0x0100210040001080ULL, 0x4100100820004100ULL, 0x0880100008000480ULL,
    0x4200100420080200ULL, 0x8100020100080400ULL, 0x0200040110886200ULL, 0x0200008040220411ULL,
    0x0404800084400220ULL, 0x0000401000402000ULL, 0x0086001081220440ULL, 0x0408800800100280ULL,
    0x000A001201040820ULL, 0x8848800200840080ULL, 0x4001000100040200ULL, 0x0442000102105084ULL,
    0x9080010020804100ULL, 0x0040404000201009ULL, 0x0000808010002009ULL, 0x2200090021D00100ULL,
    0x0008008008040080ULL, 0x0004004002010040ULL, 0x0011040008015042ULL, 0x00000A0001768104ULL,
    0x0000800080204009ULL, 0x2010004140002001ULL, 0x9800200280100080ULL, 0x1000100080080080ULL,
    0x0442000A00049020ULL, 0x2100040080020080ULL, 0x0800120400900148ULL, 0x0010040A00128541ULL,
    0x2800804000800030ULL, 0x1010002000400041ULL, 0x4000200011004100ULL, 0x0610008410800800ULL,
    0x0400802402800800ULL, 0xC100020080800400ULL, 0x0002000802000401ULL, 0x0182085882000401ULL,
    0x0220204000808000ULL, 0x2860100040024022ULL, 0x0001002004110040ULL, 0x99101042000A0020ULL,
    0x0004080004008080ULL, 0x0010040002008080ULL, 0x2012004881020004ULL, 0x8300842444820011ULL,
    0x0088403882010200ULL, 0x0820400080210100ULL, 0x0110910040A00300ULL, 0x0801100280080480ULL,
    0x0242009008200600ULL, 0x1002000489500200ULL, 0x0040800200010080ULL, 0x0091800041000080ULL,
    0x0000209300488001ULL, 0x04C1002414824001ULL, 0x020020000B001041ULL, 0x7000100004200901ULL,
    0x8002002004100802ULL, 0x30010002084C0007ULL, 0x0888221800813004ULL, 0x4000002840840112ULL,
};

static uint64_t rng_state = 0x9E3779B97F4A7C15ULL;
static uint64_t rng(void) {
    /* xorshift64* */
    rng_state ^= rng_state >> 12;
    rng_state ^= rng_state << 25;
    rng_state ^= rng_state >> 27;
    return rng_state * 2685821657736338717ULL;
}

static void init_magics(Magic *table, Bitboard *storage, const int dirs[4][2], const uint64_t *known) {
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
        for (int attempt = 0;; attempt++) {
            Bitboard magic;
            if (attempt == 0) {
                magic = known[sq]; /* zapisana liczba; gdyby nie pasowała — szukamy od nowa */
            } else {
                do {
                    magic = rng() & rng() & rng();
                } while (popcount((m->mask * magic) >> 56) < 6);
            }
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
    init_magics(BISHOP_M, BISHOP_TABLE, BISHOP_DIRS, BISHOP_MAGICS);
    init_magics(ROOK_M, ROOK_TABLE, ROOK_DIRS, ROOK_MAGICS);

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
