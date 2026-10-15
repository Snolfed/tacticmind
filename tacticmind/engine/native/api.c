/*
 * Interfejs biblioteki dla Pythona (ctypes) — patrz tacticmind/engine/native.py.
 *
 * Python steruje iterative deepening (jedna głębokość = jedno wywołanie
 * tm_iterate), żeby po każdej głębokości wysłać do interfejsu SearchInfo,
 * tak jak robił to silnik w Pythonie. Wynik ukończonej głębokości
 * tm_report zapisuje jako prosty tekst, który Python zamienia na obiekty.
 */
#include "tm.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

TM_API int tm_version(void) { return 1; }

TM_API int tm_hidden_size(void) { return NNUE_HIDDEN; }

TM_API int tm_load_net(const char *path) { return nnue_load(path); }

TM_API int tm_net_loaded(void) { return NET_LOADED; }

TM_API void *tm_engine_new(int tt_mb) { return engine_new(tt_mb); }

TM_API void tm_engine_free(void *e) { engine_free((Engine *)e); }

TM_API void tm_engine_clear(void *e) { engine_clear((Engine *)e); }

TM_API void tm_set_use_nnue(void *e, int flag) { ((Engine *)e)->pos.use_nnue = flag; }

/* Nowe wyszukiwanie: pozycja z FEN, zerowanie statystyk. Zwraca liczbę legalnych ruchów albo -1 dla złego FEN. */
TM_API int tm_begin(void *ep, const char *fen, int multipv, int record_tree) {
    Engine *e = ep;
    if (!pos_set_fen(&e->pos, fen)) return -1;
    engine_new_search(e);
    e->node_limit = 0;
    return engine_prepare(e, multipv, record_tree);
}

TM_API int tm_terminal(void *e) { return ((Engine *)e)->terminal; }

/* Jedna głębokość. stop_after_ms: limit liczony od tm_begin (< 0 — bez limitu). Zwraca 1, gdy ukończona. */
TM_API int tm_iterate(void *ep, int depth, double stop_after_ms, PollFn poll, void *user) {
    Engine *e = ep;
    e->poll = poll;
    e->poll_user = user;
    e->stop = 0;
    e->stop_at_ms = stop_after_ms >= 0 ? e->start_ms + stop_after_ms : -1;
    int ok = engine_iterate(e, depth);
    e->poll = NULL;
    return ok;
}

typedef struct {
    char *buf;
    int size;
    int len;
} Out;

static void out(Out *o, const char *fmt, ...) {
    if (o->len >= o->size - 1) return;
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(o->buf + o->len, (size_t)(o->size - o->len), fmt, ap);
    va_end(ap);
    if (n > 0) o->len += n;
    if (o->len > o->size - 1) o->len = o->size - 1;
}

/*
 * Wynik ostatniej ukończonej głębokości:
 *   stats depth seldepth nodes qnodes cutoffs tt_hits searched pruned time_ms
 *   line score ruch1 ruch2 …            (MultiPV, ocena z perspektywy strony na ruchu)
 *   node ruch score exact tt_cut        (mini-drzewo: ruch z korzenia)
 *   child ruch score bound pruned       (odpowiedź przeciwnika; bound 0 = dokładny, 1 = ≤, 2 = ≥)
 */
TM_API int tm_report(void *ep, char *buf, int size, int depth) {
    Engine *e = ep;
    Out o = {buf, size, 0};
    char uci[8];
    out(&o, "stats %d %d %llu %llu %llu %llu %llu %llu %d\n", depth, e->seldepth > depth ? e->seldepth : depth,
        (unsigned long long)e->nodes, (unsigned long long)e->qnodes, (unsigned long long)e->cutoffs,
        (unsigned long long)e->tt_hits, (unsigned long long)e->searched, (unsigned long long)e->pruned,
        (int)(now_ms() - e->start_ms));
    int k = e->multipv < e->n_root ? e->multipv : e->n_root;
    for (int i = 0; i < k; i++) {
        RootMove *rm = &e->root[i];
        if (!rm->exact && i > 0) break;
        Move pv[MAX_PLY];
        int len = engine_extend_pv(e, rm, pv, depth > rm->pv_len ? depth : rm->pv_len);
        if (len == 0) {
            pv[0] = rm->move;
            len = 1;
        }
        out(&o, "line %d", rm->score);
        for (int j = 0; j < len; j++) {
            move_to_uci(pv[j], uci);
            out(&o, " %s", uci);
        }
        out(&o, "\n");
    }
    if (e->record_tree) {
        for (int i = 0; i < e->n_root; i++) {
            RootMove *rm = &e->root[i];
            move_to_uci(rm->move, uci);
            out(&o, "node %s %d %d %d\n", uci, rm->score, rm->exact, rm->tt_cut);
            for (int j = 0; j < rm->n_children; j++) {
                TreeChild *c = &rm->children[j];
                move_to_uci(c->move, uci);
                out(&o, "child %s %d %d %d\n", uci, c->score, c->bound, c->pruned);
            }
        }
    }
    return o.len;
}

/* Ocena statyczna (perspektywa strony na ruchu) — testy i diagnostyka. */
TM_API int tm_eval(const char *fen, int use_nnue) {
    static Position pos;
    pos.use_nnue = use_nnue;
    if (!pos_set_fen(&pos, fen)) return -999999;
    return evaluate(&pos);
}

TM_API unsigned long long tm_perft(const char *fen, int depth) {
    static Position pos;
    pos.use_nnue = 0;
    if (!pos_set_fen(&pos, fen)) return 0;
    return perft(&pos, depth);
}
