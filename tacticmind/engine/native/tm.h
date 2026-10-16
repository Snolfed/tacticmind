/*
 * TacticMind — silnik szachowy w C.
 *
 * Wspólne deklaracje: bitboardy, pozycja, generator ruchów, ocena (NNUE
 * i ręczna), wyszukiwanie. Pola numerujemy a1 = 0, b1 = 1, …, h8 = 63.
 */
#ifndef TM_H
#define TM_H

#include <stdint.h>
#include <stddef.h>

#if defined(_WIN32)
#define TM_API __declspec(dllexport)
#else
#define TM_API __attribute__((visibility("default")))
#endif

typedef uint64_t Bitboard;
typedef uint16_t Move;

enum { WHITE = 0, BLACK = 1 };
enum { PAWN = 0, KNIGHT, BISHOP, ROOK, QUEEN, KING };
/* Figura = kolor * 6 + typ; NO_PIECE = puste pole. */
enum { NO_PIECE = 12 };

#define PIECE(color, type) ((color) * 6 + (type))
#define PTYPE(piece) ((piece) % 6)
#define PCOLOR(piece) ((piece) / 6)

#define BB(sq) (1ULL << (sq))
#define FILE_OF(sq) ((sq) & 7)
#define RANK_OF(sq) ((sq) >> 3)

/* Ruch w 16 bitach: z (6) | do (6) | flaga (4). */
enum {
    MF_QUIET = 0,
    MF_DOUBLE = 1,
    MF_KCASTLE = 2,
    MF_QCASTLE = 3,
    MF_CAPTURE = 4,
    MF_EP = 5,
    MF_PROMO = 8,      /* 8..11: promocja na N, B, R, Q */
    MF_PROMO_CAP = 12  /* 12..15: promocja z biciem */
};
#define MOVE(from, to, flag) ((Move)((from) | ((to) << 6) | ((flag) << 12)))
#define M_FROM(m) ((m) & 63)
#define M_TO(m) (((m) >> 6) & 63)
#define M_FLAG(m) ((m) >> 12)
#define M_IS_CAPTURE(m) (M_FLAG(m) & 4)
#define M_IS_PROMO(m) (M_FLAG(m) & 8)
#define M_PROMO_TYPE(m) ((M_FLAG(m) & 3) + KNIGHT)
#define M_IS_TACTICAL(m) (M_FLAG(m) & 12)

enum { CASTLE_WK = 1, CASTLE_WQ = 2, CASTLE_BK = 4, CASTLE_BQ = 8 };

#define MAX_MOVES 256
#define MAX_PLY 128
#define MAX_GAME 1024

#define MATE 32000
#define MATE_BOUND (MATE - 1000)
#define INF 100000

/* ------------------------------------------------------------- bitboardy */
extern Bitboard PAWN_ATT[2][64];
extern Bitboard KNIGHT_ATT[64];
extern Bitboard KING_ATT[64];
extern Bitboard BETWEEN[64][64];
extern Bitboard LINE[64][64];

void bb_init(void);
Bitboard bishop_attacks(int sq, Bitboard occ);
Bitboard rook_attacks(int sq, Bitboard occ);
static inline Bitboard queen_attacks(int sq, Bitboard occ) { return bishop_attacks(sq, occ) | rook_attacks(sq, occ); }

static inline int popcount(Bitboard b) { return __builtin_popcountll(b); }
static inline int lsb(Bitboard b) { return __builtin_ctzll(b); }
static inline int pop_lsb(Bitboard *b) {
    int s = __builtin_ctzll(*b);
    *b &= *b - 1;
    return s;
}

/* ------------------------------------------------------------- NNUE */
/* Architektura: (768 → HIDDEN) × 2 perspektywy → 1, aktywacja SCReLU. */
#define NNUE_INPUTS 768
#ifndef NNUE_HIDDEN
#define NNUE_HIDDEN 256
#endif
#define NNUE_QA 255
#define NNUE_QB 64
#define NNUE_SCALE 400
/* Kubełki wyjścia: osobna warstwa wyjściowa zależnie od liczby figur na planszy (faza gry). */
#define NNUE_MAX_BUCKETS 8
#define NNUE_BUCKET(pieces, buckets) (((pieces) - 2) * (buckets) / 31)

typedef struct {
    int16_t v[2][NNUE_HIDDEN]; /* [perspektywa][neuron] */
} Accumulator;

typedef struct {
    int16_t ft_w[NNUE_INPUTS * NNUE_HIDDEN];
    int16_t ft_b[NNUE_HIDDEN];
    int16_t out_w[NNUE_MAX_BUCKETS][2 * NNUE_HIDDEN];
    int16_t out_b[NNUE_MAX_BUCKETS];
    int buckets;
} Network;

extern Network NET;
extern int NET_LOADED;

int nnue_load(const char *path);
int nnue_load_memory(const unsigned char *data, size_t size);

/* ------------------------------------------------------------- pozycja */
typedef struct {
    uint64_t key;
    Move move;
    int8_t captured;
    uint8_t castling;
    int8_t ep;
    int16_t halfmove;
} Undo;

typedef struct {
    Bitboard pieces[12];
    Bitboard by_color[2];
    Bitboard occupied;
    int8_t board[64];
    int side;
    int castling;
    int ep;      /* pole bicia w przelocie albo -1 */
    int halfmove;
    int fullmove;
    uint64_t key;
    int ply;     /* liczba ruchów na stosie (od ustawienia FEN) */
    Undo hist[MAX_GAME];
    /* NNUE: akumulatory dla każdego poziomu stosu. */
    Accumulator acc[MAX_GAME + 1];
    int use_nnue;
} Position;

void pos_init_tables(void);
int pos_set_fen(Position *pos, const char *fen);
void pos_get_fen(const Position *pos, char *out);
void pos_make(Position *pos, Move m);
void pos_unmake(Position *pos);
void pos_make_null(Position *pos);
void pos_unmake_null(Position *pos);
int pos_attacked(const Position *pos, int sq, int by);
Bitboard pos_attackers(const Position *pos, int sq, Bitboard occ);
int pos_in_check(const Position *pos);
int pos_is_repetition(const Position *pos, int search_ply);
int pos_insufficient(const Position *pos);
void pos_refresh_acc(Position *pos);
int pos_parse_uci(Position *pos, const char *uci, Move *out);
void move_to_uci(Move m, char *out);

static inline Bitboard pos_bb(const Position *pos, int color, int type) { return pos->pieces[PIECE(color, type)]; }
static inline int king_sq(const Position *pos, int color) { return lsb(pos->pieces[PIECE(color, KING)]); }

/* ------------------------------------------------------------- ruchy */
typedef struct {
    Move moves[MAX_MOVES];
    int scores[MAX_MOVES];
    int count;
} MoveList;

void gen_moves(const Position *pos, MoveList *list, int tactical_only);
int is_legal(const Position *pos, Move m);
void gen_legal(Position *pos, MoveList *list);
int is_pseudo_legal(const Position *pos, Move m);
uint64_t perft(Position *pos, int depth);
int see_ge(const Position *pos, Move m, int threshold);

/* ------------------------------------------------------------- ocena */
int evaluate(Position *pos);       /* perspektywa strony na ruchu, centypiony */
int eval_hce(const Position *pos); /* ręczna ocena (perspektywa strony na ruchu) */
int nnue_evaluate(const Position *pos);
extern const int PIECE_VALUE[6];

/* ------------------------------------------------------------- wyszukiwanie */
typedef struct {
    uint64_t key;
    int16_t score;
    int16_t eval;
    Move move;
    uint8_t depth;
    uint8_t flag_age; /* 2 bity flagi | 6 bitów wieku */
} TTEntry;

enum { TT_NONE = 0, TT_UPPER = 1, TT_LOWER = 2, TT_EXACT = 3 };

typedef struct {
    Move move;
    int32_t score;
    uint8_t bound; /* 0 dokładny, 1 górne ograniczenie, 2 dolne */
    uint8_t pruned;
} TreeChild;

#define TREE_MAX_CHILDREN 128

typedef struct {
    Move move;
    int score;
    int exact;
    int pv_len;
    Move pv[MAX_PLY];
    uint64_t nodes; /* węzły zużyte na ten ruch (do sortowania) */
    /* mini-drzewo: odpowiedzi przeciwnika */
    int tt_cut;
    int n_children;
    TreeChild children[TREE_MAX_CHILDREN];
} RootMove;

typedef struct Engine Engine;
/* Zwraca 1, gdy trzeba przerwać. Wywoływane co ok. 20 ms. */
typedef int (*PollFn)(void *user, int depth, uint64_t nodes, uint64_t cutoffs, uint64_t tt_hits, int time_ms);

struct Engine {
    Position pos;
    TTEntry *tt;
    size_t tt_mask;
    uint8_t tt_age;

    int16_t history[2][64][64];
    Move killers[MAX_PLY + 2][2];
    Move counter[12][64];
    int16_t cont_hist[12][64][12][64]; /* historia kontynuacji (poprzedni ruch → ruch) */

    Move pv[MAX_PLY + 1][MAX_PLY + 1];
    int pv_len[MAX_PLY + 1];
    int static_eval[MAX_PLY + 4];
    int stack_piece[MAX_PLY + 4];
    int stack_to[MAX_PLY + 4];
    Move excluded[MAX_PLY + 4];

    RootMove root[MAX_MOVES];
    int n_root;
    int multipv;
    int record_tree;
    int root_side;
    int terminal; /* 0, 1 = mat, 2 = pat */
    int current_root;

    /* statystyki */
    uint64_t nodes, qnodes, cutoffs, tt_hits, searched, pruned;
    int seldepth;
    int depth;

    /* czas i przerywanie */
    double start_ms;
    double stop_at_ms; /* < 0: bez limitu */
    double last_poll_ms;
    PollFn poll;
    void *poll_user;
    volatile int stop;
    uint64_t node_limit; /* 0 = bez limitu */
};

double now_ms(void);
Engine *engine_new(int tt_mb);
void engine_free(Engine *e);
void engine_clear(Engine *e);
void engine_new_search(Engine *e);
/* Przygotowanie korzenia; zwraca liczbę legalnych ruchów. */
int engine_prepare(Engine *e, int multipv, int record_tree);
/* Jedna iteracja iterative deepening. Zwraca 1 gdy ukończona, 0 gdy przerwana. */
int engine_iterate(Engine *e, int depth);
/* Wyszukiwanie z iterative deepening do limitu czasu/głębokości/węzłów. */
Move engine_think(Engine *e, int max_depth, int time_ms, uint64_t node_limit, int *score_out, int verbose);
int engine_extend_pv(Engine *e, const RootMove *rm, Move *out, int max_len);

#endif
