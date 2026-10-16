/*
 * Wyszukiwanie: negamax z alfa-betą w wariancie PVS (Principal Variation Search).
 *
 * Względem wersji w Pythonie dochodzą techniki, które w C mają sens, bo
 * liczymy ok. 100× więcej węzłów na sekundę:
 *  - PVS: po pierwszym ruchu sprawdzamy pozostałe „zerowym oknem” (czy są
 *    lepsze od alfy?) i liczymy dokładnie tylko te, które zaskoczą,
 *  - null move pruning: gdy nawet po oddaniu ruchu przeciwnikowi pozycja jest
 *    ≥ beta, gałąź na pewno da cięcie,
 *  - late move reductions (LMR): późne, ciche ruchy liczymy płycej,
 *  - reverse futility / futility / late move pruning / przycinanie SEE:
 *    w płytkich węzłach pomijamy ruchy, które nie mają szans podnieść alfy,
 *  - historia ruchów, killery, counter-move i historia kontynuacji do porządkowania.
 *
 * MultiPV liczymy tak samo jak w Pythonie: alfa dla kolejnego ruchu
 * w korzeniu to wynik K-tego najlepszego ruchu znalezionego do tej pory.
 */
#include "tm.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#include <windows.h>
double now_ms(void) {
    static LARGE_INTEGER freq;
    LARGE_INTEGER t;
    if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart * 1000.0 / (double)freq.QuadPart;
}
#else
#include <time.h>
double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}
#endif

static int LMR[64][64];

static void init_lmr(void) {
    static int done = 0;
    if (done) return;
    for (int d = 1; d < 64; d++)
        for (int m = 1; m < 64; m++) LMR[d][m] = (int)(0.75 + log((double)d) * log((double)m) / 2.25);
    done = 1;
}

/* ------------------------------------------------------- tablica transpozycji */

Engine *engine_new(int tt_mb) {
    pos_init_tables();
    init_lmr();
    Engine *e = calloc(1, sizeof(Engine));
    if (!e) return NULL;
    size_t entries = 1;
    while (entries * 2 * sizeof(TTEntry) <= (size_t)tt_mb * 1024 * 1024) entries *= 2;
    e->tt = calloc(entries, sizeof(TTEntry));
    if (!e->tt) {
        free(e);
        return NULL;
    }
    e->tt_mask = entries - 1;
    e->pos.use_nnue = 1;
    pos_set_fen(&e->pos, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    e->stop_at_ms = -1;
    return e;
}

void engine_free(Engine *e) {
    if (!e) return;
    free(e->tt);
    free(e);
}

void engine_clear(Engine *e) {
    memset(e->tt, 0, (e->tt_mask + 1) * sizeof(TTEntry));
    memset(e->history, 0, sizeof e->history);
    memset(e->counter, 0, sizeof e->counter);
    memset(e->cont_hist, 0, sizeof e->cont_hist);
}

static inline int score_to_tt(int s, int ply) { return s > MATE_BOUND ? s + ply : s < -MATE_BOUND ? s - ply : s; }
static inline int score_from_tt(int s, int ply) { return s > MATE_BOUND ? s - ply : s < -MATE_BOUND ? s + ply : s; }

static TTEntry *tt_probe(Engine *e, uint64_t key) {
    TTEntry *t = &e->tt[key & e->tt_mask];
    return t->key == key && (t->flag_age & 3) ? t : NULL;
}

static void tt_store(Engine *e, uint64_t key, int depth, int flag, int score, int eval, Move move, int ply) {
    TTEntry *t = &e->tt[key & e->tt_mask];
    int old_age = t->flag_age >> 2;
    if (t->key != key || depth + 3 >= t->depth || flag == TT_EXACT || old_age != (e->tt_age & 63)) {
        if (move || t->key != key) t->move = move;
        t->key = key;
        t->score = (int16_t)score_to_tt(score, ply);
        t->eval = (int16_t)eval;
        t->depth = (uint8_t)(depth < 0 ? 0 : depth);
        t->flag_age = (uint8_t)(flag | ((e->tt_age & 63) << 2));
    }
}

void engine_new_search(Engine *e) {
    e->tt_age++;
    e->nodes = e->qnodes = e->cutoffs = e->tt_hits = e->searched = e->pruned = 0;
    e->seldepth = 0;
    e->stop = 0;
    memset(e->killers, 0, sizeof e->killers);
    /* Historię „postarzamy” zamiast zerować — wiedza z poprzedniej pozycji wciąż się przydaje. */
    for (int c = 0; c < 2; c++)
        for (int a = 0; a < 64; a++)
            for (int b = 0; b < 64; b++) e->history[c][a][b] /= 2;
    e->start_ms = now_ms();
    e->last_poll_ms = e->start_ms;
}

/* ------------------------------------------------------- czas i przerywanie */

static void check_time(Engine *e) {
    if (e->node_limit && e->nodes >= e->node_limit && e->depth > 1) e->stop = 1;
    if ((e->nodes & 1023) != 0) return;
    double now = now_ms();
    if (e->stop_at_ms >= 0 && now >= e->stop_at_ms && e->depth > 1) e->stop = 1;
    if (e->poll && now - e->last_poll_ms >= 20) {
        e->last_poll_ms = now;
        if (e->poll(e->poll_user, e->depth, e->nodes, e->cutoffs, e->tt_hits, (int)(now - e->start_ms))) e->stop = 1;
    }
}

/* ------------------------------------------------------- porządkowanie ruchów */

static const int MVV[6] = {100, 300, 320, 500, 900, 0};

static inline void history_update(int16_t *h, int bonus) {
    int v = *h + bonus - *h * abs(bonus) / 16384;
    *h = (int16_t)(v > 16000 ? 16000 : v < -16000 ? -16000 : v);
}

static void score_moves(Engine *e, MoveList *list, Move tt_move, int ply) {
    Position *pos = &e->pos;
    Move k1 = e->killers[ply][0], k2 = e->killers[ply][1];
    Move cm = 0;
    int prev_pc = ply > 0 ? e->stack_piece[ply - 1] : -1, prev_to = ply > 0 ? e->stack_to[ply - 1] : 0;
    if (prev_pc >= 0) cm = e->counter[prev_pc][prev_to];
    for (int i = 0; i < list->count; i++) {
        Move m = list->moves[i];
        int s;
        if (m == tt_move) {
            s = 2000000000;
        } else if (M_IS_CAPTURE(m)) {
            int victim = M_FLAG(m) == MF_EP ? PAWN : PTYPE(pos->board[M_TO(m)]);
            int attacker = PTYPE(pos->board[M_FROM(m)]);
            s = MVV[victim] * 16 - attacker;
            s += see_ge(pos, m, 0) ? 1000000 : -1000000;
            if (M_IS_PROMO(m) && M_PROMO_TYPE(m) == QUEEN) s += 5000;
        } else if (M_IS_PROMO(m)) {
            s = M_PROMO_TYPE(m) == QUEEN ? 950000 : -2000000;
        } else if (m == k1) {
            s = 900000;
        } else if (m == k2) {
            s = 800000;
        } else if (m == cm) {
            s = 700000;
        } else {
            int pc = pos->board[M_FROM(m)];
            s = e->history[pos->side][M_FROM(m)][M_TO(m)];
            if (prev_pc >= 0) s += e->cont_hist[prev_pc][prev_to][pc][M_TO(m)];
        }
        list->scores[i] = s;
    }
}

static inline Move pick(MoveList *list, int start) {
    int best = start;
    for (int j = start + 1; j < list->count; j++)
        if (list->scores[j] > list->scores[best]) best = j;
    if (best != start) {
        Move m = list->moves[start];
        int s = list->scores[start];
        list->moves[start] = list->moves[best];
        list->scores[start] = list->scores[best];
        list->moves[best] = m;
        list->scores[best] = s;
    }
    return list->moves[start];
}

static int has_non_pawn(const Position *pos, int side) {
    return (pos->by_color[side] & ~pos_bb(pos, side, PAWN) & ~pos_bb(pos, side, KING)) != 0;
}

/* ------------------------------------------------------- mini-drzewo (UI) */

static void record_child(Engine *e, Move m, int score, int alpha, int beta, int pruned) {
    RootMove *rm = &e->root[e->current_root];
    if (rm->n_children >= TREE_MAX_CHILDREN) return;
    TreeChild *c = &rm->children[rm->n_children++];
    c->move = m;
    c->score = score;
    c->pruned = (uint8_t)pruned;
    c->bound = pruned ? 0 : score <= alpha ? 1 : score >= beta ? 2 : 0;
}

/* ------------------------------------------------------- quiescence */

static int qsearch(Engine *e, int alpha, int beta, int ply) {
    Position *pos = &e->pos;
    e->nodes++;
    e->qnodes++;
    check_time(e);
    if (e->stop) return 0;
    e->pv_len[ply] = 0;
    if (ply > e->seldepth) e->seldepth = ply;
    if (ply >= MAX_PLY - 1) return evaluate(pos);
    if (pos_insufficient(pos)) return 0;

    int in_check = pos_in_check(pos);
    TTEntry *tt = tt_probe(e, pos->key);
    Move tt_move = 0;
    int pv_node = beta - alpha > 1;
    if (tt) {
        e->tt_hits++;
        tt_move = tt->move;
        int s = score_from_tt(tt->score, ply), f = tt->flag_age & 3;
        if (!pv_node && (f == TT_EXACT || (f == TT_LOWER && s >= beta) || (f == TT_UPPER && s <= alpha))) return s;
    }

    int best, stand_pat = -INF;
    if (!in_check) {
        stand_pat = tt ? tt->eval : evaluate(pos);
        if (tt && !tt->eval) stand_pat = evaluate(pos);
        if (stand_pat >= beta) return stand_pat;
        if (stand_pat > alpha) alpha = stand_pat;
        best = stand_pat;
    } else {
        best = -MATE + ply;
    }

    MoveList list;
    gen_moves(pos, &list, !in_check);
    score_moves(e, &list, tt_move, ply);
    int legal = 0;
    Move best_move = 0;
    int orig_alpha = alpha;
    for (int i = 0; i < list.count; i++) {
        Move m = pick(&list, i);
        if (!is_legal(pos, m)) continue;
        legal++;
        if (!in_check) {
            if (!M_IS_PROMO(m)) {
                int victim = M_FLAG(m) == MF_EP ? PAWN : PTYPE(pos->board[M_TO(m)]);
                /* Delta pruning: nawet zbicie tej figury z zapasem nie podniesie alfy. */
                if (stand_pat + MVV[victim] + 200 <= alpha) continue;
            }
            /* Złe bicie (traci materiał w wymianie) — w liściu pomijamy. */
            if (list.scores[i] < 0) continue;
        }
        e->stack_piece[ply] = pos->board[M_FROM(m)];
        e->stack_to[ply] = M_TO(m);
        pos_make(pos, m);
        int score = -qsearch(e, -beta, -alpha, ply + 1);
        pos_unmake(pos);
        if (e->stop) return 0;
        if (score > best) {
            best = score;
            if (score > alpha) {
                alpha = score;
                best_move = m;
                if (score >= beta) {
                    e->cutoffs++;
                    break;
                }
            }
        }
    }
    if (in_check && legal == 0) return -MATE + ply;
    int flag = best >= beta ? TT_LOWER : best > orig_alpha ? TT_EXACT : TT_UPPER;
    tt_store(e, pos->key, 0, flag, best, in_check ? 0 : stand_pat, best_move, ply);
    return best;
}

/* ------------------------------------------------------- negamax / PVS */

static int negamax(Engine *e, int depth, int alpha, int beta, int ply, int cut_node) {
    Position *pos = &e->pos;
    int pv_node = beta - alpha > 1;
    /* Mini-drzewo zapisujemy w węzłach poziomu 1 (odpowiedzi przeciwnika), ale nie w pomocniczym
       wyszukiwaniu „singular extension”, które odwiedza ten sam węzeł jeszcze raz. */
    int recording = e->record_tree && ply == 1 && !e->excluded[ply];
    e->pv_len[ply] = 0;
    if (recording) {
        e->root[e->current_root].n_children = 0;
        e->root[e->current_root].tt_cut = 0;
    }
    if (ply >= MAX_PLY - 1) return evaluate(pos);

    /* Remisy: powtórzenie, brak materiału, reguła 50 ruchów (ale mat w setnym półruchu wygrywa). */
    if (pos_is_repetition(pos, ply) || pos_insufficient(pos)) return 0;
    if (pos->halfmove >= 100) {
        if (!pos_in_check(pos)) return 0;
        MoveList legal;
        gen_legal(pos, &legal);
        return legal.count ? 0 : -MATE + ply;
    }

    /* Mate distance pruning: nie szukaj mata dłuższego niż już znaleziony. */
    int ma = alpha > -MATE + ply ? alpha : -MATE + ply;
    int mb = beta < MATE - ply - 1 ? beta : MATE - ply - 1;
    if (ma >= mb) return ma;

    int in_check = pos_in_check(pos);
    if (in_check) depth++; /* przedłużenie szacha */
    if (depth <= 0) return qsearch(e, alpha, beta, ply);

    e->nodes++;
    check_time(e);
    if (e->stop) return 0;
    if (ply > e->seldepth) e->seldepth = ply;

    Move excluded = e->excluded[ply];
    TTEntry *tt = excluded ? NULL : tt_probe(e, pos->key);
    Move tt_move = 0;
    int tt_score = 0, tt_flag = TT_NONE, tt_depth = -1;
    if (tt) {
        e->tt_hits++;
        tt_move = tt->move;
        tt_score = score_from_tt(tt->score, ply);
        tt_flag = tt->flag_age & 3;
        tt_depth = tt->depth;
        if (!pv_node && tt_depth >= depth &&
            (tt_flag == TT_EXACT || (tt_flag == TT_LOWER && tt_score >= beta) || (tt_flag == TT_UPPER && tt_score <= alpha))) {
            if (recording) e->root[e->current_root].tt_cut = 1;
            return tt_score;
        }
    }

    int eval;
    if (in_check) {
        eval = -INF;
    } else {
        eval = tt && tt->eval ? tt->eval : evaluate(pos);
        /* Wynik z TT jest dokładniejszy niż ocena statyczna, jeśli granica na to pozwala. */
        if (tt && ((tt_flag == TT_LOWER && tt_score > eval) || (tt_flag == TT_UPPER && tt_score < eval)) && abs(tt_score) < MATE_BOUND)
            eval = tt_score;
    }
    e->static_eval[ply] = eval;
    int improving = !in_check && ply >= 2 && eval > e->static_eval[ply - 2];
    e->killers[ply + 1][0] = e->killers[ply + 1][1] = 0;

    if (!pv_node && !in_check && !excluded) {
        /* Reverse futility pruning: przewaga tak duża, że płytkie liczenie jej nie zmieni. */
        if (depth <= 8 && eval - 80 * (depth - improving) >= beta && eval < MATE_BOUND) return eval;

        /* Null move pruning: oddajemy ruch; jeśli i tak jest ≥ beta, gałąź da cięcie. */
        if (depth >= 3 && eval >= beta && ply > 0 && e->stack_piece[ply - 1] >= 0 && has_non_pawn(pos, pos->side)) {
            int r = 3 + depth / 4 + ((eval - beta) / 200 < 3 ? (eval - beta) / 200 : 3);
            e->stack_piece[ply] = -1;
            e->stack_to[ply] = 0;
            pos_make_null(pos);
            int score = -negamax(e, depth - 1 - r, -beta, -beta + 1, ply + 1, !cut_node);
            pos_unmake_null(pos);
            if (e->stop) return 0;
            if (score >= beta) return score >= MATE_BOUND ? beta : score;
        }

        /* Razoring: beznadziejnie słaba pozycja na małej głębokości — sprawdzamy tylko bicia. */
        if (depth <= 3 && eval + 250 * depth < alpha) {
            int score = qsearch(e, alpha - 1, alpha, ply);
            if (e->stop) return 0;
            if (score < alpha) return score;
        }
    }

    /* Internal iterative reduction: bez ruchu z TT liczymy płycej. */
    if (!tt_move && depth >= 4 && !excluded) depth--;

    MoveList list;
    gen_moves(pos, &list, 0);
    score_moves(e, &list, tt_move, ply);

    int orig_alpha = alpha;
    int best = -INF;
    Move best_move = 0;
    int legal = 0, quiets_tried = 0;
    Move quiets[MAX_MOVES];
    int prev_pc = ply > 0 ? e->stack_piece[ply - 1] : -1, prev_to = ply > 0 ? e->stack_to[ply - 1] : 0;

    for (int i = 0; i < list.count; i++) {
        Move m = pick(&list, i);
        if (m == excluded) continue;
        if (!is_legal(pos, m)) continue;
        legal++;
        int quiet = !M_IS_TACTICAL(m);
        int pc = pos->board[M_FROM(m)];

        /* Przycinanie płytkich, późnych ruchów (tylko gdy mamy już ruch, który nie przegrywa). */
        if (best > -MATE_BOUND && has_non_pawn(pos, pos->side)) {
            if (quiet && depth <= 8 && quiets_tried >= (3 + depth * depth) / (2 - improving)) {
                e->pruned++;
                if (recording) record_child(e, m, 0, alpha, beta, 1);
                continue;
            }
            if (quiet && !in_check && depth <= 8 && eval + 100 + 100 * depth <= alpha) {
                e->pruned++;
                if (recording) record_child(e, m, 0, alpha, beta, 1);
                continue;
            }
            if (depth <= 8 && !see_ge(pos, m, quiet ? -60 * depth : -25 * depth * depth)) {
                e->pruned++;
                if (recording) record_child(e, m, 0, alpha, beta, 1);
                continue;
            }
        }

        /* Singular extension: ruch z TT dużo lepszy od reszty — przedłużamy go. */
        int extension = 0;
        if (m == tt_move && !excluded && ply > 0 && depth >= 7 && tt_flag != TT_UPPER && tt_depth >= depth - 3 &&
            abs(tt_score) < MATE_BOUND) {
            int sbeta = tt_score - 2 * depth;
            e->excluded[ply] = m;
            int s = negamax(e, (depth - 1) / 2, sbeta - 1, sbeta, ply, cut_node);
            e->excluded[ply] = 0;
            if (e->stop) return 0;
            if (s < sbeta)
                extension = 1;
            else if (sbeta >= beta)
                return sbeta; /* multi-cut */
        }

        e->stack_piece[ply] = pc;
        e->stack_to[ply] = M_TO(m);
        pos_make(pos, m);
        e->searched++;
        int new_depth = depth - 1 + extension;
        int score;
        if (legal > 1 + pv_node && depth >= 3 && (quiet || list.scores[i] < 0)) {
            int r = LMR[depth < 64 ? depth : 63][legal < 64 ? legal : 63];
            r -= pv_node;
            r += cut_node;
            r += !improving;
            if (quiet) r -= (e->history[pos->side ^ 1][M_FROM(m)][M_TO(m)]) / 6000;
            if (pos_in_check(pos)) r--;
            if (r < 0) r = 0;
            if (r > new_depth - 1) r = new_depth - 1;
            score = -negamax(e, new_depth - r, -alpha - 1, -alpha, ply + 1, 1);
            if (score > alpha && r > 0) score = -negamax(e, new_depth, -alpha - 1, -alpha, ply + 1, !cut_node);
        } else if (!pv_node || legal > 1) {
            score = -negamax(e, new_depth, -alpha - 1, -alpha, ply + 1, !cut_node);
        } else {
            score = alpha + 1; /* pierwszy ruch w węźle PV: od razu pełne okno */
        }
        if (pv_node && (legal == 1 || (score > alpha && score < beta))) score = -negamax(e, new_depth, -beta, -alpha, ply + 1, 0);
        pos_unmake(pos);
        if (e->stop) return 0;
        if (recording) record_child(e, m, score, alpha, beta, 0);

        if (score > best) {
            best = score;
            if (score > alpha) {
                best_move = m;
                alpha = score;
                e->pv[ply][0] = m;
                memcpy(&e->pv[ply][1], e->pv[ply + 1], sizeof(Move) * (size_t)e->pv_len[ply + 1]);
                e->pv_len[ply] = e->pv_len[ply + 1] + 1;
                if (score >= beta) {
                    e->cutoffs++;
                    /* Ruchy, których alfa-beta w ogóle nie sprawdziła. */
                    for (int j = i + 1; j < list.count; j++) {
                        if (!is_legal(pos, list.moves[j])) continue;
                        e->pruned++;
                        if (recording) record_child(e, list.moves[j], 0, alpha, beta, 1);
                    }
                    if (quiet) {
                        int bonus = depth * depth * 16 < 1600 ? depth * depth * 16 : 1600;
                        if (e->killers[ply][0] != m) {
                            e->killers[ply][1] = e->killers[ply][0];
                            e->killers[ply][0] = m;
                        }
                        history_update(&e->history[pos->side][M_FROM(m)][M_TO(m)], bonus);
                        if (prev_pc >= 0) {
                            e->counter[prev_pc][prev_to] = m;
                            history_update(&e->cont_hist[prev_pc][prev_to][pc][M_TO(m)], bonus);
                        }
                        for (int q = 0; q < quiets_tried; q++) {
                            Move qm = quiets[q];
                            history_update(&e->history[pos->side][M_FROM(qm)][M_TO(qm)], -bonus);
                            if (prev_pc >= 0) history_update(&e->cont_hist[prev_pc][prev_to][pos->board[M_FROM(qm)]][M_TO(qm)], -bonus);
                        }
                    }
                    break;
                }
            }
        }
        if (quiet && quiets_tried < MAX_MOVES) quiets[quiets_tried++] = m;
    }

    if (legal == 0) return excluded ? alpha : in_check ? -MATE + ply : 0;
    if (!excluded) {
        int flag = best >= beta ? TT_LOWER : best > orig_alpha ? TT_EXACT : TT_UPPER;
        tt_store(e, pos->key, depth, flag, best, in_check ? 0 : e->static_eval[ply], best_move, ply);
    }
    return best;
}

/* ------------------------------------------------------- korzeń */

int engine_prepare(Engine *e, int multipv, int record_tree) {
    MoveList list;
    gen_legal(&e->pos, &list);
    e->n_root = list.count;
    e->multipv = multipv < 1 ? 1 : multipv;
    e->record_tree = record_tree;
    e->root_side = e->pos.side;
    e->terminal = 0;
    e->depth = 0;
    pos_refresh_acc(&e->pos);
    /* Ocena korzenia — punkt odniesienia dla „improving” na poziomie 2. */
    e->static_eval[0] = pos_in_check(&e->pos) ? -INF : evaluate(&e->pos);
    score_moves(e, &list, 0, 0);
    for (int i = 0; i < list.count; i++) {
        Move m = pick(&list, i);
        RootMove *rm = &e->root[i];
        memset(rm, 0, sizeof *rm - sizeof rm->children);
        rm->move = m;
        rm->score = -INF;
        rm->pv[0] = m;
        rm->pv_len = 1;
    }
    if (list.count == 0) e->terminal = pos_in_check(&e->pos) ? 1 : 2;
    for (int i = 0; i < MAX_PLY + 4; i++) {
        e->stack_piece[i] = 0;
        e->excluded[i] = 0;
    }
    return list.count;
}

static int cmp_root(const void *a, const void *b) {
    const RootMove *x = a, *y = b;
    if (x->score != y->score) return y->score > x->score ? 1 : -1;
    if (x->exact != y->exact) return y->exact - x->exact;
    return y->nodes > x->nodes ? 1 : y->nodes < x->nodes ? -1 : 0;
}

int engine_iterate(Engine *e, int depth) {
    Position *pos = &e->pos;
    int k = e->multipv < e->n_root ? e->multipv : e->n_root;
    int top[MAX_MOVES];
    int n_top = 0;
    e->depth = depth;
    for (int i = 0; i < e->n_root; i++) {
        RootMove *rm = &e->root[i];
        int alpha = n_top >= k ? top[k - 1] : -INF;
        e->current_root = i;
        uint64_t nodes_before = e->nodes;
        e->stack_piece[0] = pos->board[M_FROM(rm->move)];
        e->stack_to[0] = M_TO(rm->move);
        pos_make(pos, rm->move);
        e->searched++;
        int score;
        if (i == 0 && k == 1 && depth >= 5 && abs(rm->score) < MATE_BOUND) {
            /* Okno aspiracyjne: zakładamy, że wynik będzie blisko poprzedniego; gdy nie — poszerzamy. */
            int delta = 20, a = rm->score - delta, b = rm->score + delta;
            for (;;) {
                score = -negamax(e, depth - 1, -b, -a, 1, 0);
                if (e->stop) break;
                if (score <= a) {
                    a = score - delta > -INF ? score - delta : -INF;
                } else if (score >= b) {
                    b = score + delta < INF ? score + delta : INF;
                } else {
                    break;
                }
                delta *= 2;
                if (delta > 800) a = -INF, b = INF;
            }
        } else if (alpha == -INF) {
            score = -negamax(e, depth - 1, -INF, INF, 1, 0);
        } else {
            score = -negamax(e, depth - 1, -alpha - 1, -alpha, 1, 1);
            if (score > alpha && !e->stop) score = -negamax(e, depth - 1, -INF, -alpha, 1, 0);
        }
        pos_unmake(pos);
        if (e->stop) return 0;
        rm->nodes = e->nodes - nodes_before;
        rm->score = score;
        rm->exact = score > alpha;
        if (rm->exact) {
            rm->pv[0] = rm->move;
            memcpy(&rm->pv[1], e->pv[1], sizeof(Move) * (size_t)e->pv_len[1]);
            rm->pv_len = e->pv_len[1] + 1;
            int j = n_top < k ? n_top++ : k - 1;
            while (j > 0 && top[j - 1] < score) {
                top[j] = top[j - 1];
                j--;
            }
            top[j] = score;
        }
    }
    /* Kolejność na następną iterację: najlepsze dokładne wyniki na początku. */
    qsort(e->root, (size_t)e->n_root, sizeof(RootMove), cmp_root);
    RootMove *best = &e->root[0];
    tt_store(e, pos->key, depth, TT_EXACT, best->score, 0, best->move, 0);
    return 1;
}

/* Dociąga wariant z tablicy transpozycji, gdy jest krótszy niż głębokość. */
int engine_extend_pv(Engine *e, const RootMove *rm, Move *out, int max_len) {
    Position *pos = &e->pos;
    int n = 0;
    for (int i = 0; i < rm->pv_len && n < MAX_PLY - 1; i++) {
        MoveList legal;
        gen_legal(pos, &legal);
        int ok = 0;
        for (int j = 0; j < legal.count; j++) ok |= legal.moves[j] == rm->pv[i];
        if (!ok) break;
        out[n++] = rm->pv[i];
        pos_make(pos, rm->pv[i]);
    }
    while (n < max_len && n < MAX_PLY - 1) {
        TTEntry *t = tt_probe(e, pos->key);
        if (!t || !t->move) break;
        MoveList legal;
        gen_legal(pos, &legal);
        int ok = 0;
        for (int j = 0; j < legal.count; j++) ok |= legal.moves[j] == t->move;
        if (!ok) break;
        out[n++] = t->move;
        pos_make(pos, t->move);
        if (pos_is_repetition(pos, 64)) break;
    }
    for (int i = 0; i < n; i++) pos_unmake(pos);
    return n;
}

Move engine_think(Engine *e, int max_depth, int time_ms, uint64_t node_limit, int *score_out, int verbose) {
    engine_new_search(e);
    e->node_limit = node_limit;
    e->stop_at_ms = time_ms > 0 ? e->start_ms + time_ms : -1;
    int n = engine_prepare(e, 1, 0);
    if (score_out) *score_out = 0;
    if (n == 0) return 0;
    Move best = e->root[0].move;
    int best_score = 0;
    for (int d = 1; d <= max_depth && d < MAX_PLY - 4; d++) {
        if (d > 1 && time_ms > 0 && now_ms() - e->start_ms > time_ms * 0.5) break;
        if (d > 1 && node_limit && e->nodes >= node_limit) break;
        if (!engine_iterate(e, d)) break;
        best = e->root[0].move;
        best_score = e->root[0].score;
        if (verbose) {
            double el = now_ms() - e->start_ms;
            char buf[8];
            Move pv[MAX_PLY];
            int len = engine_extend_pv(e, &e->root[0], pv, d);
            if (abs(best_score) > MATE_BOUND) {
                int plies = MATE - abs(best_score);
                printf("info depth %d seldepth %d score mate %d", d, e->seldepth, best_score > 0 ? (plies + 1) / 2 : -(plies + 1) / 2);
            } else {
                printf("info depth %d seldepth %d score cp %d", d, e->seldepth, best_score);
            }
            printf(" nodes %llu nps %llu time %d pv", (unsigned long long)e->nodes, (unsigned long long)(e->nodes * 1000 / (el > 1 ? el : 1)),
                   (int)el);
            for (int i = 0; i < len; i++) {
                move_to_uci(pv[i], buf);
                printf(" %s", buf);
            }
            printf("\n");
            fflush(stdout);
        }
        if (abs(best_score) > MATE_BOUND && d >= 2 * (MATE - abs(best_score)) + 4) break;
    }
    if (score_out) *score_out = best_score;
    return best;
}
