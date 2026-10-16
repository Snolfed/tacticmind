/*
 * Move generator: pseudo-legal moves from bitboards, legality checked
 * separately (whether our king is left in check after the move), SEE and perft.
 */
#include "tm.h"

static inline void add(MoveList *l, int from, int to, int flag) { l->moves[l->count++] = MOVE(from, to, flag); }

static void add_promos(MoveList *l, int from, int to, int capture, int tactical_only) {
    int base = capture ? MF_PROMO_CAP : MF_PROMO;
    add(l, from, to, base + 3); /* queen */
    if (tactical_only && !capture) return;
    add(l, from, to, base + 0);
    add(l, from, to, base + 1);
    add(l, from, to, base + 2);
}

void gen_moves(const Position *pos, MoveList *list, int tactical_only) {
    list->count = 0;
    int us = pos->side, them = us ^ 1;
    Bitboard own = pos->by_color[us], enemy = pos->by_color[them], occ = pos->occupied, empty = ~occ;

    /* Pawns */
    Bitboard pawns = pos_bb(pos, us, PAWN);
    int up = us == WHITE ? 8 : -8;
    Bitboard promo_rank = us == WHITE ? 0xFF00000000000000ULL : 0xFFULL;
    Bitboard third_rank = us == WHITE ? 0xFF0000ULL : 0xFF0000000000ULL;
    Bitboard single = us == WHITE ? (pawns << 8) & empty : (pawns >> 8) & empty;
    Bitboard b = single & promo_rank;
    while (b) {
        int to = pop_lsb(&b);
        add_promos(list, to - up, to, 0, tactical_only);
    }
    if (!tactical_only) {
        b = single & ~promo_rank;
        while (b) {
            int to = pop_lsb(&b);
            add(list, to - up, to, MF_QUIET);
        }
        Bitboard dbl = us == WHITE ? ((single & third_rank) << 8) & empty : ((single & third_rank) >> 8) & empty;
        while (dbl) {
            int to = pop_lsb(&dbl);
            add(list, to - 2 * up, to, MF_DOUBLE);
        }
    }
    Bitboard p = pawns;
    while (p) {
        int from = pop_lsb(&p);
        Bitboard att = PAWN_ATT[us][from] & enemy;
        while (att) {
            int to = pop_lsb(&att);
            if (BB(to) & promo_rank)
                add_promos(list, from, to, 1, tactical_only);
            else
                add(list, from, to, MF_CAPTURE);
        }
        if (pos->ep >= 0 && (PAWN_ATT[us][from] & BB(pos->ep))) add(list, from, pos->ep, MF_EP);
    }

    /* Pieces */
    Bitboard targets = tactical_only ? enemy : ~own;
    for (int type = KNIGHT; type <= KING; type++) {
        Bitboard pcs = pos_bb(pos, us, type);
        while (pcs) {
            int from = pop_lsb(&pcs);
            Bitboard att;
            switch (type) {
                case KNIGHT: att = KNIGHT_ATT[from]; break;
                case BISHOP: att = bishop_attacks(from, occ); break;
                case ROOK: att = rook_attacks(from, occ); break;
                case QUEEN: att = queen_attacks(from, occ); break;
                default: att = KING_ATT[from]; break;
            }
            att &= targets;
            while (att) {
                int to = pop_lsb(&att);
                add(list, from, to, (BB(to) & enemy) ? MF_CAPTURE : MF_QUIET);
            }
        }
    }

    /* Castling (empty squares; checks are verified by is_legal) */
    if (!tactical_only && pos->castling) {
        if (us == WHITE) {
            if ((pos->castling & CASTLE_WK) && !(occ & 0x60ULL)) add(list, 4, 6, MF_KCASTLE);
            if ((pos->castling & CASTLE_WQ) && !(occ & 0x0EULL)) add(list, 4, 2, MF_QCASTLE);
        } else {
            if ((pos->castling & CASTLE_BK) && !(occ & 0x6000000000000000ULL)) add(list, 60, 62, MF_KCASTLE);
            if ((pos->castling & CASTLE_BQ) && !(occ & 0x0E00000000000000ULL)) add(list, 60, 58, MF_QCASTLE);
        }
    }
}

int is_legal(const Position *pos, Move m) {
    int us = pos->side, them = us ^ 1;
    int from = M_FROM(m), to = M_TO(m), flag = M_FLAG(m);
    int ksq = king_sq(pos, us);
    Bitboard enemy = pos->by_color[them];
    if (from == ksq) {
        if (flag == MF_KCASTLE || flag == MF_QCASTLE) {
            int mid = flag == MF_KCASTLE ? from + 1 : from - 1;
            return !pos_attacked(pos, from, them) && !pos_attacked(pos, mid, them) && !pos_attacked(pos, to, them);
        }
        Bitboard occ = pos->occupied ^ BB(from);
        return !(pos_attackers(pos, to, occ) & enemy & ~BB(to));
    }
    Bitboard occ = (pos->occupied ^ BB(from)) | BB(to);
    Bitboard removed = BB(to);
    if (flag == MF_EP) {
        int cap = to + (us == WHITE ? -8 : 8);
        occ ^= BB(cap);
        removed |= BB(cap);
    }
    return !(pos_attackers(pos, ksq, occ) & enemy & ~removed);
}

void gen_legal(Position *pos, MoveList *list) {
    MoveList all;
    gen_moves(pos, &all, 0);
    list->count = 0;
    for (int i = 0; i < all.count; i++)
        if (is_legal(pos, all.moves[i])) list->moves[list->count++] = all.moves[i];
}

/* Whether a move (e.g. from the transposition table or a killer) is pseudo-legal in this position. */
int is_pseudo_legal(const Position *pos, Move m) {
    if (!m) return 0;
    int from = M_FROM(m), to = M_TO(m);
    int pc = pos->board[from];
    if (pc == NO_PIECE || PCOLOR(pc) != pos->side) return 0;
    MoveList list;
    /* Simple and safe: generate this piece's moves. */
    gen_moves(pos, &list, 0);
    for (int i = 0; i < list.count; i++)
        if (list.moves[i] == m) return 1;
    (void)to;
    return 0;
}

uint64_t perft(Position *pos, int depth) {
    MoveList list;
    gen_moves(pos, &list, 0);
    uint64_t n = 0;
    for (int i = 0; i < list.count; i++) {
        Move m = list.moves[i];
        if (!is_legal(pos, m)) continue;
        if (depth <= 1) {
            n++;
            continue;
        }
        pos_make(pos, m);
        n += perft(pos, depth - 1);
        pos_unmake(pos);
    }
    return n;
}

const int PIECE_VALUE[6] = {100, 320, 330, 500, 950, 20000};
static const int SEE_VALUE[6] = {100, 320, 330, 500, 950, 0};

/* Static Exchange Evaluation: whether the exchange on the target square yields at least `threshold`. */
int see_ge(const Position *pos, Move m, int threshold) {
    if (M_FLAG(m) == MF_KCASTLE || M_FLAG(m) == MF_QCASTLE || M_FLAG(m) == MF_EP || M_IS_PROMO(m)) return 0 >= threshold;
    int from = M_FROM(m), to = M_TO(m);
    int swap = (pos->board[to] != NO_PIECE ? SEE_VALUE[PTYPE(pos->board[to])] : 0) - threshold;
    if (swap < 0) return 0;
    swap = SEE_VALUE[PTYPE(pos->board[from])] - swap;
    if (swap <= 0) return 1;
    Bitboard occ = pos->occupied ^ BB(from) ^ BB(to);
    int stm = pos->side;
    Bitboard attackers = pos_attackers(pos, to, occ) & occ;
    Bitboard diag = pos->pieces[2] | pos->pieces[8] | pos->pieces[4] | pos->pieces[10];
    Bitboard orth = pos->pieces[3] | pos->pieces[9] | pos->pieces[4] | pos->pieces[10];
    int res = 1;
    for (;;) {
        stm ^= 1;
        attackers &= occ;
        Bitboard mine = attackers & pos->by_color[stm];
        if (!mine) break;
        res ^= 1;
        int type;
        Bitboard bb = 0;
        for (type = PAWN; type <= KING; type++) {
            bb = mine & pos_bb(pos, stm, type);
            if (bb) break;
        }
        if (type == KING) {
            /* The king may capture only when the opponent has no defenders left. */
            return (attackers & pos->by_color[stm ^ 1]) ? res ^ 1 : res;
        }
        swap = SEE_VALUE[type] - swap;
        if (swap < res) break;
        occ ^= BB(lsb(bb));
        if (type == PAWN || type == BISHOP || type == QUEEN) attackers |= bishop_attacks(to, occ) & diag;
        if (type == ROOK || type == QUEEN) attackers |= rook_attacks(to, occ) & orth;
    }
    return res;
}
