/*
 * Pozycja: FEN, wykonywanie i cofanie ruchów, hasz Zobrista, ataki na pola.
 *
 * Przy każdym ruchu aktualizujemy też przyrostowo akumulator sieci NNUE:
 * zamiast liczyć pierwszą warstwę od zera (768 wejść × 256 neuronów),
 * dodajemy i odejmujemy tylko wagi figur, które się ruszyły (2–4 kolumny).
 */
#include "tm.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>

static uint64_t Z_PIECE[12][64];
static uint64_t Z_CASTLE[16];
static uint64_t Z_EP[8];
static uint64_t Z_SIDE;

/* Maska praw do roszady, które zostają po ruchu z/na dane pole. */
static int CASTLE_MASK[64];

void nnue_refresh(const Position *pos, Accumulator *acc);
void nnue_update(Accumulator *dst, const Accumulator *src, const int *add, int nadd, const int *sub, int nsub);

static inline int feature(int persp, int piece, int sq) {
    if (persp == WHITE) return PCOLOR(piece) * 384 + PTYPE(piece) * 64 + sq;
    return (1 - PCOLOR(piece)) * 384 + PTYPE(piece) * 64 + (sq ^ 56);
}

void pos_init_tables(void) {
    static int done = 0;
    if (done) return;
    bb_init();
    uint64_t s = 0x2545F4914F6CDD1DULL;
#define NEXT() (s ^= s << 13, s ^= s >> 7, s ^= s << 17, s)
    for (int p = 0; p < 12; p++)
        for (int q = 0; q < 64; q++) Z_PIECE[p][q] = NEXT();
    for (int i = 0; i < 16; i++) Z_CASTLE[i] = NEXT();
    for (int i = 0; i < 8; i++) Z_EP[i] = NEXT();
    Z_SIDE = NEXT();
#undef NEXT
    for (int i = 0; i < 64; i++) CASTLE_MASK[i] = 15;
    CASTLE_MASK[0] &= ~CASTLE_WQ;
    CASTLE_MASK[7] &= ~CASTLE_WK;
    CASTLE_MASK[4] &= ~(CASTLE_WK | CASTLE_WQ);
    CASTLE_MASK[56] &= ~CASTLE_BQ;
    CASTLE_MASK[63] &= ~CASTLE_BK;
    CASTLE_MASK[60] &= ~(CASTLE_BK | CASTLE_BQ);
    done = 1;
}

static inline void put(Position *pos, int pc, int sq) {
    pos->pieces[pc] |= BB(sq);
    pos->by_color[PCOLOR(pc)] |= BB(sq);
    pos->occupied |= BB(sq);
    pos->board[sq] = (int8_t)pc;
}

static inline void take(Position *pos, int pc, int sq) {
    pos->pieces[pc] &= ~BB(sq);
    pos->by_color[PCOLOR(pc)] &= ~BB(sq);
    pos->occupied &= ~BB(sq);
    pos->board[sq] = NO_PIECE;
}

static uint64_t compute_key(const Position *pos) {
    uint64_t k = 0;
    for (int sq = 0; sq < 64; sq++)
        if (pos->board[sq] != NO_PIECE) k ^= Z_PIECE[pos->board[sq]][sq];
    k ^= Z_CASTLE[pos->castling];
    if (pos->ep >= 0) k ^= Z_EP[FILE_OF(pos->ep)];
    if (pos->side == BLACK) k ^= Z_SIDE;
    return k;
}

void pos_refresh_acc(Position *pos) {
    if (pos->use_nnue) nnue_refresh(pos, &pos->acc[pos->ply]);
}

int pos_set_fen(Position *pos, const char *fen) {
    pos_init_tables();
    int use_nnue = pos->use_nnue;
    memset(pos->pieces, 0, sizeof pos->pieces);
    memset(pos->by_color, 0, sizeof pos->by_color);
    pos->occupied = 0;
    for (int i = 0; i < 64; i++) pos->board[i] = NO_PIECE;
    const char *p = fen;
    while (*p == ' ') p++;
    int rank = 7, file = 0;
    static const char *CHARS = "PNBRQKpnbrqk";
    for (; *p && *p != ' '; p++) {
        if (*p == '/') {
            if (file != 8) return 0;
            rank--;
            file = 0;
        } else if (*p >= '1' && *p <= '8') {
            file += *p - '0';
        } else {
            const char *c = strchr(CHARS, *p);
            if (!c || file > 7 || rank < 0) return 0;
            put(pos, (int)(c - CHARS), rank * 8 + file);
            file++;
        }
    }
    if (rank != 0 || file != 8) return 0;
    if (popcount(pos->pieces[PIECE(WHITE, KING)]) != 1 || popcount(pos->pieces[PIECE(BLACK, KING)]) != 1) return 0;
    while (*p == ' ') p++;
    pos->side = (*p == 'b') ? BLACK : WHITE;
    if (*p) p++;
    while (*p == ' ') p++;
    pos->castling = 0;
    for (; *p && *p != ' '; p++) {
        if (*p == 'K') pos->castling |= CASTLE_WK;
        if (*p == 'Q') pos->castling |= CASTLE_WQ;
        if (*p == 'k') pos->castling |= CASTLE_BK;
        if (*p == 'q') pos->castling |= CASTLE_BQ;
    }
    /* Prawa do roszady tylko, gdy król i wieża stoją na swoich polach. */
    if (pos->board[4] != PIECE(WHITE, KING)) pos->castling &= ~(CASTLE_WK | CASTLE_WQ);
    if (pos->board[7] != PIECE(WHITE, ROOK)) pos->castling &= ~CASTLE_WK;
    if (pos->board[0] != PIECE(WHITE, ROOK)) pos->castling &= ~CASTLE_WQ;
    if (pos->board[60] != PIECE(BLACK, KING)) pos->castling &= ~(CASTLE_BK | CASTLE_BQ);
    if (pos->board[63] != PIECE(BLACK, ROOK)) pos->castling &= ~CASTLE_BK;
    if (pos->board[56] != PIECE(BLACK, ROOK)) pos->castling &= ~CASTLE_BQ;
    while (*p == ' ') p++;
    pos->ep = -1;
    if (*p >= 'a' && *p <= 'h' && p[1] >= '1' && p[1] <= '8') {
        int sq = (p[1] - '1') * 8 + (p[0] - 'a');
        /* Pole bicia w przelocie zapamiętujemy tylko, gdy bicie jest w ogóle możliwe (spójny hasz). */
        if (PAWN_ATT[pos->side ^ 1][sq] & pos->pieces[PIECE(pos->side, PAWN)]) pos->ep = sq;
        p += 2;
    } else if (*p) {
        p++;
    }
    pos->halfmove = 0;
    pos->fullmove = 1;
    int hm = 0, fm = 1;
    if (sscanf(p, "%d %d", &hm, &fm) >= 1) {
        pos->halfmove = hm;
        pos->fullmove = fm > 0 ? fm : 1;
    }
    pos->ply = 0;
    pos->key = compute_key(pos);
    pos->use_nnue = use_nnue;
    pos_refresh_acc(pos);
    return 1;
}

void pos_get_fen(const Position *pos, char *out) {
    static const char *CHARS = "PNBRQKpnbrqk";
    char *o = out;
    for (int r = 7; r >= 0; r--) {
        int empty = 0;
        for (int f = 0; f < 8; f++) {
            int pc = pos->board[r * 8 + f];
            if (pc == NO_PIECE) {
                empty++;
            } else {
                if (empty) *o++ = (char)('0' + empty);
                empty = 0;
                *o++ = CHARS[pc];
            }
        }
        if (empty) *o++ = (char)('0' + empty);
        if (r) *o++ = '/';
    }
    *o++ = ' ';
    *o++ = pos->side == WHITE ? 'w' : 'b';
    *o++ = ' ';
    if (!pos->castling) *o++ = '-';
    if (pos->castling & CASTLE_WK) *o++ = 'K';
    if (pos->castling & CASTLE_WQ) *o++ = 'Q';
    if (pos->castling & CASTLE_BK) *o++ = 'k';
    if (pos->castling & CASTLE_BQ) *o++ = 'q';
    *o++ = ' ';
    if (pos->ep >= 0) {
        *o++ = (char)('a' + FILE_OF(pos->ep));
        *o++ = (char)('1' + RANK_OF(pos->ep));
    } else {
        *o++ = '-';
    }
    sprintf(o, " %d %d", pos->halfmove, pos->fullmove);
}

Bitboard pos_attackers(const Position *pos, int sq, Bitboard occ) {
    Bitboard bishops = pos->pieces[PIECE(WHITE, BISHOP)] | pos->pieces[PIECE(BLACK, BISHOP)] |
                       pos->pieces[PIECE(WHITE, QUEEN)] | pos->pieces[PIECE(BLACK, QUEEN)];
    Bitboard rooks = pos->pieces[PIECE(WHITE, ROOK)] | pos->pieces[PIECE(BLACK, ROOK)] |
                     pos->pieces[PIECE(WHITE, QUEEN)] | pos->pieces[PIECE(BLACK, QUEEN)];
    return (PAWN_ATT[BLACK][sq] & pos->pieces[PIECE(WHITE, PAWN)]) |
           (PAWN_ATT[WHITE][sq] & pos->pieces[PIECE(BLACK, PAWN)]) |
           (KNIGHT_ATT[sq] & (pos->pieces[PIECE(WHITE, KNIGHT)] | pos->pieces[PIECE(BLACK, KNIGHT)])) |
           (KING_ATT[sq] & (pos->pieces[PIECE(WHITE, KING)] | pos->pieces[PIECE(BLACK, KING)])) |
           (bishop_attacks(sq, occ) & bishops) | (rook_attacks(sq, occ) & rooks);
}

int pos_attacked(const Position *pos, int sq, int by) {
    if (PAWN_ATT[by ^ 1][sq] & pos->pieces[PIECE(by, PAWN)]) return 1;
    if (KNIGHT_ATT[sq] & pos->pieces[PIECE(by, KNIGHT)]) return 1;
    if (KING_ATT[sq] & pos->pieces[PIECE(by, KING)]) return 1;
    Bitboard q = pos->pieces[PIECE(by, QUEEN)];
    if (bishop_attacks(sq, pos->occupied) & (pos->pieces[PIECE(by, BISHOP)] | q)) return 1;
    if (rook_attacks(sq, pos->occupied) & (pos->pieces[PIECE(by, ROOK)] | q)) return 1;
    return 0;
}

int pos_in_check(const Position *pos) { return pos_attacked(pos, king_sq(pos, pos->side), pos->side ^ 1); }

void pos_make(Position *pos, Move m) {
    Undo *u = &pos->hist[pos->ply];
    u->key = pos->key;
    u->move = m;
    u->castling = (uint8_t)pos->castling;
    u->ep = (int8_t)pos->ep;
    u->halfmove = (int16_t)pos->halfmove;
    u->captured = NO_PIECE;

    int us = pos->side, them = us ^ 1;
    int from = M_FROM(m), to = M_TO(m), flag = M_FLAG(m);
    int pc = pos->board[from];
    uint64_t key = pos->key ^ Z_SIDE;
    int add[2] = {0, 0}, sub[2] = {0, 0}, nadd = 0, nsub = 0; /* zmiany dla NNUE: (figura*64 + pole) */

    if (pos->ep >= 0) key ^= Z_EP[FILE_OF(pos->ep)];
    pos->ep = -1;
    pos->halfmove++;

    if (flag == MF_EP) {
        int cap_sq = to + (us == WHITE ? -8 : 8);
        int cap = PIECE(them, PAWN);
        take(pos, cap, cap_sq);
        key ^= Z_PIECE[cap][cap_sq];
        u->captured = (int8_t)cap;
        sub[nsub++] = cap * 64 + cap_sq;
    } else if (M_IS_CAPTURE(m)) {
        int cap = pos->board[to];
        take(pos, cap, to);
        key ^= Z_PIECE[cap][to];
        u->captured = (int8_t)cap;
        sub[nsub++] = cap * 64 + to;
    }
    if (u->captured != NO_PIECE || PTYPE(pc) == PAWN) pos->halfmove = 0;

    take(pos, pc, from);
    key ^= Z_PIECE[pc][from];
    sub[nsub++] = pc * 64 + from;
    int placed = M_IS_PROMO(m) ? PIECE(us, M_PROMO_TYPE(m)) : pc;
    put(pos, placed, to);
    key ^= Z_PIECE[placed][to];
    add[nadd++] = placed * 64 + to;

    if (flag == MF_KCASTLE || flag == MF_QCASTLE) {
        int rook = PIECE(us, ROOK);
        int rf = flag == MF_KCASTLE ? to + 1 : to - 2;
        int rt = flag == MF_KCASTLE ? to - 1 : to + 1;
        take(pos, rook, rf);
        put(pos, rook, rt);
        key ^= Z_PIECE[rook][rf] ^ Z_PIECE[rook][rt];
        sub[nsub++] = rook * 64 + rf;
        add[nadd++] = rook * 64 + rt;
    } else if (flag == MF_DOUBLE) {
        int ep = to + (us == WHITE ? -8 : 8);
        if (PAWN_ATT[us][ep] & pos->pieces[PIECE(them, PAWN)]) {
            pos->ep = ep;
            key ^= Z_EP[FILE_OF(ep)];
        }
    }

    key ^= Z_CASTLE[pos->castling];
    pos->castling &= CASTLE_MASK[from] & CASTLE_MASK[to];
    key ^= Z_CASTLE[pos->castling];

    pos->side = them;
    if (us == BLACK) pos->fullmove++;
    pos->key = key;
    pos->ply++;
    if (pos->use_nnue) nnue_update(&pos->acc[pos->ply], &pos->acc[pos->ply - 1], add, nadd, sub, nsub);
}

void pos_unmake(Position *pos) {
    pos->ply--;
    Undo *u = &pos->hist[pos->ply];
    Move m = u->move;
    int them = pos->side, us = them ^ 1;
    int from = M_FROM(m), to = M_TO(m), flag = M_FLAG(m);
    int placed = pos->board[to];
    int pc = M_IS_PROMO(m) ? PIECE(us, PAWN) : placed;
    take(pos, placed, to);
    put(pos, pc, from);
    if (flag == MF_EP) {
        put(pos, u->captured, to + (us == WHITE ? -8 : 8));
    } else if (u->captured != NO_PIECE) {
        put(pos, u->captured, to);
    }
    if (flag == MF_KCASTLE || flag == MF_QCASTLE) {
        int rook = PIECE(us, ROOK);
        int rf = flag == MF_KCASTLE ? to + 1 : to - 2;
        int rt = flag == MF_KCASTLE ? to - 1 : to + 1;
        take(pos, rook, rt);
        put(pos, rook, rf);
    }
    pos->side = us;
    if (us == BLACK) pos->fullmove--;
    pos->castling = u->castling;
    pos->ep = u->ep;
    pos->halfmove = u->halfmove;
    pos->key = u->key;
}

void pos_make_null(Position *pos) {
    Undo *u = &pos->hist[pos->ply];
    u->key = pos->key;
    u->move = 0;
    u->castling = (uint8_t)pos->castling;
    u->ep = (int8_t)pos->ep;
    u->halfmove = (int16_t)pos->halfmove;
    u->captured = NO_PIECE;
    if (pos->ep >= 0) pos->key ^= Z_EP[FILE_OF(pos->ep)];
    pos->ep = -1;
    pos->key ^= Z_SIDE;
    pos->side ^= 1;
    pos->halfmove++;
    pos->ply++;
    if (pos->use_nnue) pos->acc[pos->ply] = pos->acc[pos->ply - 1];
}

void pos_unmake_null(Position *pos) {
    pos->ply--;
    Undo *u = &pos->hist[pos->ply];
    pos->side ^= 1;
    pos->ep = u->ep;
    pos->halfmove = u->halfmove;
    pos->key = u->key;
}

int pos_is_repetition(const Position *pos, int search_ply) {
    /* Powtórzenie w obrębie przeszukiwania liczymy już przy pierwszym razie (2-krotne),
       sprzed korzenia — dopiero przy trzecim wystąpieniu. */
    int count = 0;
    int limit = pos->halfmove < pos->ply ? pos->halfmove : pos->ply;
    for (int i = 4; i <= limit; i += 2) {
        if (pos->hist[pos->ply - i].key == pos->key) {
            if (i < search_ply) return 1;
            if (++count >= 2) return 1;
        }
    }
    return 0;
}

int pos_insufficient(const Position *pos) {
    Bitboard pawns_rq = pos->pieces[0] | pos->pieces[3] | pos->pieces[4] | pos->pieces[6] | pos->pieces[9] | pos->pieces[10];
    if (pawns_rq) return 0;
    int minors = popcount(pos->pieces[1] | pos->pieces[2] | pos->pieces[7] | pos->pieces[8]);
    return minors <= 1;
}

void move_to_uci(Move m, char *out) {
    if (!m) {
        strcpy(out, "0000");
        return;
    }
    int from = M_FROM(m), to = M_TO(m);
    out[0] = (char)('a' + FILE_OF(from));
    out[1] = (char)('1' + RANK_OF(from));
    out[2] = (char)('a' + FILE_OF(to));
    out[3] = (char)('1' + RANK_OF(to));
    out[4] = 0;
    if (M_IS_PROMO(m)) {
        out[4] = "nbrq"[M_PROMO_TYPE(m) - KNIGHT];
        out[5] = 0;
    }
}

int pos_parse_uci(Position *pos, const char *uci, Move *out) {
    MoveList list;
    gen_legal(pos, &list);
    char buf[8];
    for (int i = 0; i < list.count; i++) {
        move_to_uci(list.moves[i], buf);
        if (strncmp(buf, uci, strlen(buf)) == 0 && (uci[strlen(buf)] == 0 || isspace((unsigned char)uci[strlen(buf)]))) {
            *out = list.moves[i];
            return 1;
        }
    }
    return 0;
}

/* Pomocnicze dla nnue.c */
int nnue_feature(int persp, int piece, int sq) { return feature(persp, piece, sq); }
