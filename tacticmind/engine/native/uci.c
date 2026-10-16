/*
 * Program „tmengine”: protokół UCI (mecze z innymi silnikami, np. w Cute Chess
 * albo przez python-chess) oraz narzędzia: perft, bench i generowanie danych
 * treningowych dla sieci NNUE (partie silnika z samym sobą).
 *
 *   tmengine                         — tryb UCI
 *   tmengine bench [głębokość]       — szybkość na stałym zestawie pozycji
 *   tmengine perft <głębokość> [FEN]
 *   tmengine datagen <plik> <partie> <węzły> <ziarno> [sieć.nnue]
 */
#include "tm.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <io.h>
#include <windows.h>
#else
#include <sys/select.h>
#include <unistd.h>
#endif

#define START_FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

static Engine *E;

/* ------------------------------------------------------- wejście UCI
   Czytamy stdin sami, bez bufora stdio: w trakcie liczenia (co ok. 20 ms) sprawdzamy, czy GUI
   nie przysłało „stop” albo „quit”. Bufor stdio mógłby schować te polecenia przed select(). */
static char in_buf[1 << 16];
static size_t in_len;
static int in_eof, quit_requested;

static int stdin_ready(void) {
#ifdef _WIN32
    static HANDLE h;
    static int is_pipe = -1;
    if (is_pipe < 0) {
        DWORD mode;
        h = GetStdHandle(STD_INPUT_HANDLE);
        is_pipe = !GetConsoleMode(h, &mode);
    }
    if (is_pipe) {
        DWORD avail = 0;
        if (!PeekNamedPipe(h, NULL, 0, NULL, &avail, NULL)) return 1; /* zamknięty potok: read() zwróci koniec */
        return avail > 0;
    }
    DWORD events = 0;
    GetNumberOfConsoleInputEvents(h, &events);
    return events > 1;
#else
    fd_set set;
    FD_ZERO(&set);
    FD_SET(0, &set);
    struct timeval tv = {0, 0};
    return select(1, &set, NULL, NULL, &tv) > 0;
#endif
}

/* Następna linia wejścia do out. Zwraca 1 — jest linia, 0 — na razie nic (tylko gdy !block), −1 — koniec wejścia. */
static int next_line(char *out, size_t size, int block) {
    for (;;) {
        char *nl = memchr(in_buf, '\n', in_len);
        if (nl || in_eof || in_len == sizeof in_buf) {
            size_t n = nl ? (size_t)(nl - in_buf) + 1 : in_len;
            if (n == 0) return -1;
            size_t copy = n < size ? n : size - 1;
            memcpy(out, in_buf, copy);
            out[copy] = 0;
            memmove(in_buf, in_buf + n, in_len - n);
            in_len -= n;
            return 1;
        }
        if (!block && !stdin_ready()) return 0;
#ifdef _WIN32
        int got = _read(0, in_buf + in_len, (unsigned)(sizeof in_buf - in_len));
#else
        ssize_t got = read(0, in_buf + in_len, sizeof in_buf - in_len);
#endif
        if (got <= 0) in_eof = 1;
        else in_len += (size_t)got;
    }
}

/* Wywoływane z wyszukiwania co ok. 20 ms: 1 = przerwij. */
static int uci_poll(void *user, int depth, uint64_t nodes, uint64_t cutoffs, uint64_t tt_hits, int time_ms) {
    (void)user, (void)depth, (void)nodes, (void)cutoffs, (void)tt_hits, (void)time_ms;
    char line[16384];
    int r;
    while ((r = next_line(line, sizeof line, 0)) == 1) {
        if (!strncmp(line, "isready", 7)) {
            printf("readyok\n");
            fflush(stdout);
        } else if (!strncmp(line, "stop", 4)) {
            return 1;
        } else if (!strncmp(line, "quit", 4)) {
            quit_requested = 1;
            return 1;
        }
    }
    if (r < 0) quit_requested = 1;
    return r < 0;
}

static void cmd_position(char *line) {
    char *p = strstr(line, "startpos");
    char *moves = strstr(line, "moves");
    if (p && (!moves || p < moves)) {
        pos_set_fen(&E->pos, START_FEN);
    } else if ((p = strstr(line, "fen"))) {
        char fen[256] = {0};
        size_t n = moves ? (size_t)(moves - (p + 4)) : strlen(p + 4);
        if (n > 255) n = 255;
        memcpy(fen, p + 4, n);
        if (!pos_set_fen(&E->pos, fen)) pos_set_fen(&E->pos, START_FEN);
    }
    if (moves) {
        char *tok = strtok(moves + 5, " \t\r\n");
        while (tok) {
            Move m;
            if (!pos_parse_uci(&E->pos, tok, &m)) break;
            pos_make(&E->pos, m);
            if (E->pos.ply > MAX_GAME - 200) { /* bardzo długa partia: zaczynamy historię od nowa */
                char fen[256];
                pos_get_fen(&E->pos, fen);
                pos_set_fen(&E->pos, fen);
            }
            tok = strtok(NULL, " \t\r\n");
        }
    }
}

static long arg_value(const char *line, const char *name, long def) {
    const char *p = strstr(line, name);
    if (!p) return def;
    return atol(p + strlen(name));
}

static void cmd_go(char *line) {
    line[strcspn(line, "\r\n")] = 0;
    strcat(line, " "); /* żeby „go depth 5” na końcu linii też pasowało do " depth " */
    int depth = (int)arg_value(line, " depth ", MAX_PLY - 8);
    long movetime = arg_value(line, " movetime ", 0);
    long nodes = arg_value(line, " nodes ", 0);
    long mytime = arg_value(line, E->pos.side == WHITE ? " wtime " : " btime ", LONG_MIN);
    long inc = arg_value(line, E->pos.side == WHITE ? " winc " : " binc ", 0);
    long mtg = arg_value(line, " movestogo ", 0);
    int infinite = strstr(line, " infinite") != NULL;
    int time_ms = 0;
    if (movetime > 0) {
        time_ms = (int)movetime;
    } else if (mytime != LONG_MIN) {
        if (mytime < 0) mytime = 0; /* czas już przekroczony — ruch jak najszybciej */
        if (inc < 0) inc = 0;
        long base = mytime / (mtg > 0 ? mtg + 2 : 25) + inc * 3 / 4;
        long t = base * 2;
        long cap = mytime / 2 - 30;
        if (t > cap) t = cap;
        if (t < 5) t = 5;
        time_ms = (int)t;
    }
    int score;
    E->poll = uci_poll;
    Move best = engine_think(E, depth, time_ms, (uint64_t)nodes, &score, 1);
    /* „go infinite”: bestmove dopiero po „stop”, nawet jeśli wyszukiwanie skończyło się wcześniej. */
    if (infinite && !E->stop) {
        char cmd[16384];
        int r;
        while ((r = next_line(cmd, sizeof cmd, 1)) == 1) {
            if (!strncmp(cmd, "isready", 7)) {
                printf("readyok\n");
                fflush(stdout);
            } else if (!strncmp(cmd, "stop", 4)) {
                break;
            } else if (!strncmp(cmd, "quit", 4)) {
                quit_requested = 1;
                break;
            }
        }
        if (r < 0) quit_requested = 1;
    }
    char buf[8];
    move_to_uci(best, buf);
    printf("bestmove %s\n", buf);
    fflush(stdout);
}

static void uci_loop(void) {
    char line[16384];
    while (!quit_requested && next_line(line, sizeof line - 2, 1) == 1) {
        if (!strncmp(line, "ucinewgame", 10)) {
            engine_clear(E);
        } else if (!strncmp(line, "uci", 3)) {
            printf("id name TacticMind %s\nid author TacticMind\n", NET_LOADED ? "NNUE" : "HCE");
            printf("option name Hash type spin default 64 min 1 max 4096\n");
            printf("option name EvalFile type string default tacticmind.nnue\n");
            printf("option name UseNNUE type check default true\nuciok\n");
        } else if (!strncmp(line, "isready", 7)) {
            printf("readyok\n");
        } else if (!strncmp(line, "setoption", 9)) {
            char *v = strstr(line, "value ");
            if (v) {
                v += 6;
                v[strcspn(v, "\r\n")] = 0;
                if (strstr(line, "name EvalFile")) {
                    if (!nnue_load(v)) printf("info string nie udalo sie wczytac sieci %s\n", v);
                } else if (strstr(line, "name Hash")) {
                    Engine *bigger = engine_new(atoi(v) > 0 ? atoi(v) : 1);
                    if (bigger) { /* zachowujemy pozycję i ustawienie UseNNUE */
                        bigger->pos = E->pos;
                        engine_free(E);
                        E = bigger;
                    } else {
                        printf("info string brak pamieci na Hash %s MB\n", v);
                    }
                } else if (strstr(line, "name UseNNUE")) {
                    E->pos.use_nnue = strstr(v, "true") != NULL;
                    pos_refresh_acc(&E->pos);
                }
            }
        } else if (!strncmp(line, "position", 8)) {
            cmd_position(line);
        } else if (!strncmp(line, "go", 2)) {
            cmd_go(line);
        } else if (!strncmp(line, "eval", 4)) {
            printf("eval %d (hce %d)\n", evaluate(&E->pos), eval_hce(&E->pos));
        } else if (!strncmp(line, "quit", 4)) {
            break;
        }
        fflush(stdout);
    }
}

static const char *BENCH[] = {
    START_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
    "r2q1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R1BQ1RK1 w - - 0 10",
    "rnbq1rk1/ppp1ppbp/3p1np1/8/2PPP3/2N2N2/PP2BPPP/R1BQK2R b KQ - 3 6",
    "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1",
    "4rrk1/pp1n3p/3q2pQ/2p1pb2/2PP4/2P3N1/P2B2PP/4RRK1 b - - 7 19",
    "r1bq1rk1/1pp2pbp/p1np1np1/4p3/2PPP3/2N1BP2/PP1Q2PP/R3KBNR w KQ - 0 9",
    "8/8/1p6/p1p5/P1P2k2/1P3p2/5K2/8 w - - 0 50",
};

static void bench(int depth) {
    uint64_t total = 0;
    double start = now_ms();
    for (size_t i = 0; i < sizeof BENCH / sizeof BENCH[0]; i++) {
        engine_clear(E);
        pos_set_fen(&E->pos, BENCH[i]);
        int score;
        Move m = engine_think(E, depth, 0, 0, &score, 0);
        char buf[8];
        move_to_uci(m, buf);
        printf("%-80s %6s %6d %10llu\n", BENCH[i], buf, score, (unsigned long long)E->nodes);
        total += E->nodes;
    }
    double el = now_ms() - start;
    printf("nodes %llu time %.0f ms nps %.0f\n", (unsigned long long)total, el, total * 1000.0 / el);
}

/* ------------------------------------------------------- dane treningowe */

typedef struct {
    uint64_t occ;
    uint8_t pcs[16]; /* kody figur (0..11) po dwie na bajt, w kolejności bitów occ */
    int16_t score;   /* ocena z perspektywy białych */
    uint8_t result;  /* 0 = wygrały czarne, 1 = remis, 2 = wygrały białe */
    uint8_t stm;
    uint8_t pad[4];
} PackedPos;

static uint64_t rng_s;
static uint64_t rnd(void) {
    rng_s ^= rng_s << 13;
    rng_s ^= rng_s >> 7;
    rng_s ^= rng_s << 17;
    return rng_s;
}

static void pack(const Position *pos, int score_white, PackedPos *out) {
    memset(out, 0, sizeof *out);
    out->occ = pos->occupied;
    Bitboard b = pos->occupied;
    int i = 0;
    while (b) {
        int sq = pop_lsb(&b);
        out->pcs[i / 2] |= (uint8_t)(pos->board[sq] << ((i & 1) * 4));
        i++;
    }
    out->score = (int16_t)score_white;
    out->stm = (uint8_t)pos->side;
}

static int datagen(const char *path, int games, int nodes, uint64_t seed) {
    FILE *f = fopen(path, "ab");
    if (!f) return 1;
    rng_s = seed * 0x9E3779B97F4A7C15ULL + 1;
    static PackedPos buf[1024];
    long total = 0;
    double start = now_ms();
    for (int g = 0; g < games; g++) {
        engine_clear(E);
        Position *pos = &E->pos;
        pos_set_fen(pos, START_FEN);
        /* Losowe otwarcie: 8–9 przypadkowych półruchów, żeby partie się różniły. */
        int random_plies = 8 + (int)(rnd() % 2), ok = 1;
        for (int i = 0; i < random_plies; i++) {
            MoveList l;
            gen_legal(pos, &l);
            if (!l.count) {
                ok = 0;
                break;
            }
            pos_make(pos, l.moves[rnd() % (unsigned)l.count]);
        }
        if (!ok) continue;
        { /* od nowa z FEN, żeby nie przepełnić historii */
            char fen[256];
            pos_get_fen(pos, fen);
            pos_set_fen(pos, fen);
        }
        int n = 0, result = 1, win_streak = 0, draw_streak = 0, plies = 0;
        for (;;) {
            MoveList l;
            gen_legal(pos, &l);
            if (!l.count) {
                result = pos_in_check(pos) ? (pos->side == WHITE ? 0 : 2) : 1;
                break;
            }
            if (pos->halfmove >= 100 || pos_insufficient(pos) || pos_is_repetition(pos, 0) || plies >= 400) {
                result = 1;
                break;
            }
            int score;
            Move m = engine_think(E, MAX_PLY - 8, 0, (uint64_t)nodes, &score, 0);
            int white = pos->side == WHITE ? score : -score;
            if (abs(score) >= 2000) {
                if (++win_streak >= 6) {
                    result = white > 0 ? 2 : 0;
                    break;
                }
            } else {
                win_streak = 0;
            }
            if (plies >= 80 && abs(score) <= 10) {
                if (++draw_streak >= 12) {
                    result = 1;
                    break;
                }
            } else {
                draw_streak = 0;
            }
            if (!pos_in_check(pos) && !M_IS_TACTICAL(m) && abs(score) < MATE_BOUND && n < 1024) pack(pos, white, &buf[n++]);
            pos_make(pos, m);
            plies++;
            if (pos->ply > MAX_GAME - 200) {
                char fen[256];
                pos_get_fen(pos, fen);
                pos_set_fen(pos, fen);
            }
        }
        for (int i = 0; i < n; i++) buf[i].result = (uint8_t)result;
        fwrite(buf, sizeof(PackedPos), (size_t)n, f);
        total += n;
        if ((g + 1) % 20 == 0) {
            fflush(f);
            fprintf(stderr, "partie %d/%d, pozycje %ld, %.0f poz/s\n", g + 1, games, total, total * 1000.0 / (now_ms() - start));
        }
    }
    fclose(f);
    return 0;
}

int main(int argc, char **argv) {
    pos_init_tables();
    E = engine_new(64);
    setvbuf(stdout, NULL, _IOLBF, 0);
    /* Sieć: z argumentu datagen, z TM_NET albo z pliku obok programu. */
    const char *net = getenv("TM_NET");
    if (net) nnue_load(net);
    if (!NET_LOADED) nnue_load("tacticmind.nnue");
    if (!NET_LOADED && argc > 0) {
        char path[1024];
        strncpy(path, argv[0], sizeof path - 32);
        path[sizeof path - 32] = 0;
        char *slash = strrchr(path, '/');
        if (!slash) slash = strrchr(path, '\\');
        if (slash) {
            strcpy(slash + 1, "tacticmind.nnue");
            nnue_load(path);
            if (!NET_LOADED) { /* program w native/build/, sieć w native/ */
                strcpy(slash + 1, "../tacticmind.nnue");
                nnue_load(path);
            }
        }
    }
    if (argc >= 2 && !strcmp(argv[1], "bench")) {
        bench(argc >= 3 ? atoi(argv[2]) : 12);
    } else if (argc >= 3 && !strcmp(argv[1], "perft")) {
        pos_set_fen(&E->pos, argc >= 4 ? argv[3] : START_FEN);
        double t = now_ms();
        unsigned long long n = perft(&E->pos, atoi(argv[2]));
        printf("perft %s: %llu (%.0f ms)\n", argv[2], n, now_ms() - t);
    } else if (argc >= 6 && !strcmp(argv[1], "datagen")) {
        if (argc >= 7) {
            if (!strcmp(argv[6], "hce")) {
                NET_LOADED = 0;
            } else if (!nnue_load(argv[6])) {
                fprintf(stderr, "nie udalo sie wczytac %s\n", argv[6]);
                return 1;
            }
        }
        fprintf(stderr, "ocena: %s\n", NET_LOADED ? "NNUE" : "recznie (HCE)");
        return datagen(argv[2], atoi(argv[3]), atoi(argv[4]), (uint64_t)atoll(argv[5]));
    } else {
        uci_loop();
    }
    engine_free(E);
    return 0;
}
