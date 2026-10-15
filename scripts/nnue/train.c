/*
 * Trener sieci NNUE dla TacticMind (CPU, OpenMP).
 *
 * Uczy sieć (768 → 256) × 2 → 1 z aktywacją SCReLU na pozycjach z gier
 * silnika z samym sobą (tmengine datagen). Cel uczenia to mieszanka:
 *   λ · sigmoid(ocena_silnika / 400) + (1 − λ) · wynik_partii
 * a funkcja straty to błąd kwadratowy między tym celem a sigmoid(wyjście sieci).
 * Optymalizator: Adam. Na koniec wagi są kwantowane do int16 i zapisywane
 * w formacie, który czyta tacticmind/engine/native/nnue.c.
 *
 * Kompilacja i użycie (patrz scripts/nnue/README.md):
 *   gcc -O3 -march=native -fopenmp scripts/nnue/train.c -o train -lm
 *   ./train -o tacticmind.nnue -e 30 -l 0.75 dane1.bin dane2.bin …
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _OPENMP
#include <omp.h>
#endif

#define INPUTS 768
#define HIDDEN 256
#define QA 255
#define QB 64
#define SCALE 400.0f
#define BATCH 16384
#define CLIP 1.98f

typedef struct {
    uint64_t occ;
    uint8_t pcs[16];
    int16_t score;
    uint8_t result;
    uint8_t stm;
    uint8_t pad[4];
} PackedPos;

typedef struct {
    float ft_w[INPUTS * HIDDEN];
    float ft_b[HIDDEN];
    float out_w[2 * HIDDEN];
    float out_b;
} Params;

#define NPARAMS (INPUTS * HIDDEN + HIDDEN + 2 * HIDDEN + 1)

static Params P, M1, M2;
static float lambda_eval = 0.75f;

static uint64_t rs = 88172645463325252ULL;
static uint64_t rnd(void) {
    rs ^= rs << 13;
    rs ^= rs >> 7;
    rs ^= rs << 17;
    return rs;
}
static float frand(void) { return (float)((rnd() >> 11) * (1.0 / 9007199254740992.0)); }

static int features(const PackedPos *p, int *fw, int *fb) {
    uint64_t b = p->occ;
    int n = 0;
    while (b) {
        int sq = __builtin_ctzll(b);
        b &= b - 1;
        int pc = (p->pcs[n / 2] >> ((n & 1) * 4)) & 15;
        int color = pc / 6, type = pc % 6;
        fw[n] = color * 384 + type * 64 + sq;
        fb[n] = (1 - color) * 384 + type * 64 + (sq ^ 56);
        n++;
    }
    return n;
}

static inline float sigmoidf(float x) { return 1.0f / (1.0f + expf(-x)); }

/* Przejście w przód (i opcjonalnie wstecz) dla jednej pozycji. Zwraca stratę. */
static float run(const PackedPos *p, Params *grad) {
    int fw[32], fb[32];
    int n = features(p, fw, fb);
    float acc[2][HIDDEN];
    for (int persp = 0; persp < 2; persp++) {
        int *f = persp == 0 ? fw : fb;
        float *a = acc[persp];
        memcpy(a, P.ft_b, sizeof(float) * HIDDEN);
        for (int i = 0; i < n; i++) {
            const float *w = &P.ft_w[f[i] * HIDDEN];
            for (int j = 0; j < HIDDEN; j++) a[j] += w[j];
        }
    }
    int us = p->stm, them = us ^ 1;
    float out = P.out_b;
    for (int j = 0; j < HIDDEN; j++) {
        float x = acc[us][j] < 0 ? 0 : acc[us][j] > 1 ? 1 : acc[us][j];
        float y = acc[them][j] < 0 ? 0 : acc[them][j] > 1 ? 1 : acc[them][j];
        out += x * x * P.out_w[j] + y * y * P.out_w[HIDDEN + j];
    }
    float score_stm = p->stm == 0 ? p->score : -p->score;
    float result_stm = p->stm == 0 ? p->result / 2.0f : 1.0f - p->result / 2.0f;
    float target = lambda_eval * sigmoidf(score_stm / SCALE) + (1 - lambda_eval) * result_stm;
    float pred = sigmoidf(out);
    float err = pred - target;
    if (!grad) return err * err;

    float dout = 2 * err * pred * (1 - pred);
    grad->out_b += dout;
    float dacc[2][HIDDEN];
    for (int j = 0; j < HIDDEN; j++) {
        float x = acc[us][j], y = acc[them][j];
        float cx = x < 0 ? 0 : x > 1 ? 1 : x, cy = y < 0 ? 0 : y > 1 ? 1 : y;
        grad->out_w[j] += dout * cx * cx;
        grad->out_w[HIDDEN + j] += dout * cy * cy;
        dacc[us][j] = (x > 0 && x < 1) ? dout * P.out_w[j] * 2 * x : 0;
        dacc[them][j] = (y > 0 && y < 1) ? dout * P.out_w[HIDDEN + j] * 2 * y : 0;
    }
    for (int j = 0; j < HIDDEN; j++) grad->ft_b[j] += dacc[0][j] + dacc[1][j];
    for (int persp = 0; persp < 2; persp++) {
        int *f = persp == 0 ? fw : fb;
        for (int i = 0; i < n; i++) {
            float *g = &grad->ft_w[f[i] * HIDDEN];
            for (int j = 0; j < HIDDEN; j++) g[j] += dacc[persp][j];
        }
    }
    return err * err;
}

static void save(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) {
        perror(path);
        exit(1);
    }
    uint32_t hdr[2] = {1, HIDDEN};
    fwrite("TMNN", 1, 4, f);
    fwrite(hdr, 4, 2, f);
    int16_t *q = malloc(sizeof(int16_t) * NPARAMS);
    size_t k = 0;
    for (int i = 0; i < INPUTS * HIDDEN; i++) q[k++] = (int16_t)lrintf(P.ft_w[i] * QA);
    for (int i = 0; i < HIDDEN; i++) q[k++] = (int16_t)lrintf(P.ft_b[i] * QA);
    for (int i = 0; i < 2 * HIDDEN; i++) q[k++] = (int16_t)lrintf(P.out_w[i] * QB);
    float ob = P.out_b * QA * QB;
    q[k++] = (int16_t)(ob > 32767 ? 32767 : ob < -32768 ? -32768 : lrintf(ob));
    fwrite(q, sizeof(int16_t), k, f); /* zakładamy little-endian (x86, ARM) */
    free(q);
    fclose(f);
}

int main(int argc, char **argv) {
    const char *out_path = "tacticmind.nnue";
    int epochs = 30;
    float lr = 0.001f;
    const char *init = NULL;
    char **files = malloc(sizeof(char *) * (size_t)argc);
    int nfiles = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc) out_path = argv[++i];
        else if (!strcmp(argv[i], "-e") && i + 1 < argc) epochs = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-l") && i + 1 < argc) lambda_eval = (float)atof(argv[++i]);
        else if (!strcmp(argv[i], "-r") && i + 1 < argc) lr = (float)atof(argv[++i]);
        else if (!strcmp(argv[i], "-i") && i + 1 < argc) init = argv[++i];
        else files[nfiles++] = argv[i];
    }
    /* Wczytanie danych */
    size_t total = 0, cap = 1 << 20;
    PackedPos *data = malloc(sizeof(PackedPos) * cap);
    for (int i = 0; i < nfiles; i++) {
        FILE *f = fopen(files[i], "rb");
        if (!f) {
            perror(files[i]);
            return 1;
        }
        for (;;) {
            if (total + 65536 > cap) {
                cap *= 2;
                data = realloc(data, sizeof(PackedPos) * cap);
            }
            size_t got = fread(data + total, sizeof(PackedPos), 65536, f);
            total += got;
            if (got < 65536) break;
        }
        fclose(f);
    }
    if (total < 1000) {
        fprintf(stderr, "za malo danych (%zu)\n", total);
        return 1;
    }
    for (size_t i = total - 1; i > 0; i--) { /* tasowanie */
        size_t j = rnd() % (i + 1);
        PackedPos t = data[i];
        data[i] = data[j];
        data[j] = t;
    }
    size_t nval = total / 100 < 200000 ? total / 100 : 200000;
    size_t ntrain = total - nval;
    PackedPos *val = data + ntrain;
    fprintf(stderr, "pozycje: %zu (trening %zu, walidacja %zu), lambda %.2f\n", total, ntrain, nval, lambda_eval);

    /* Inicjalizacja wag */
    if (init) {
        fprintf(stderr, "start z %s nieobslugiwany — losowa inicjalizacja\n", init);
    }
    for (int i = 0; i < INPUTS * HIDDEN; i++) P.ft_w[i] = (frand() * 2 - 1) * 0.1f;
    for (int i = 0; i < 2 * HIDDEN; i++) P.out_w[i] = (frand() * 2 - 1) * 0.05f;

    int threads = 1;
#ifdef _OPENMP
    threads = omp_get_max_threads();
#endif
    Params *grads = calloc((size_t)threads, sizeof(Params));
    const float b1 = 0.9f, b2 = 0.999f, eps = 1e-8f;
    long step = 0;
    float *pp = (float *)&P, *m1 = (float *)&M1, *m2 = (float *)&M2;
    size_t batches = ntrain / BATCH;
    time_t t0 = time(NULL);
    for (int epoch = 1; epoch <= epochs; epoch++) {
        /* Spadek kroku uczenia: ×0.3 po 60% i po 85% epok */
        float cur_lr = lr * (epoch > epochs * 0.6 ? 0.3f : 1.0f) * (epoch > epochs * 0.85 ? 0.3f : 1.0f);
        double train_loss = 0;
        for (size_t b = 0; b < batches; b++) {
            memset(grads, 0, sizeof(Params) * (size_t)threads);
            double loss = 0;
#pragma omp parallel for reduction(+ : loss) schedule(static)
            for (int i = 0; i < BATCH; i++) {
                int t = 0;
#ifdef _OPENMP
                t = omp_get_thread_num();
#endif
                loss += run(&data[b * BATCH + (size_t)i], &grads[t]);
            }
            train_loss += loss / BATCH;
            step++;
            float c1 = 1 - powf(b1, (float)step), c2 = 1 - powf(b2, (float)step);
#pragma omp parallel for schedule(static)
            for (long k = 0; k < NPARAMS; k++) {
                float g = 0;
                for (int t = 0; t < threads; t++) g += ((float *)&grads[t])[k];
                g /= BATCH;
                m1[k] = b1 * m1[k] + (1 - b1) * g;
                m2[k] = b2 * m2[k] + (1 - b2) * g * g;
                float v = pp[k] - cur_lr * (m1[k] / c1) / (sqrtf(m2[k] / c2) + eps);
                pp[k] = v > CLIP ? CLIP : v < -CLIP ? -CLIP : v;
            }
        }
        double vloss = 0;
#pragma omp parallel for reduction(+ : vloss)
        for (long i = 0; i < (long)nval; i++) vloss += run(&val[i], NULL);
        fprintf(stderr, "epoka %2d  lr %.5f  strata trening %.6f  walidacja %.6f  (%lds)\n", epoch, cur_lr, train_loss / batches,
                vloss / nval, (long)(time(NULL) - t0));
        save(out_path);
        /* tasowanie części treningowej między epokami */
        for (size_t i = ntrain - 1; i > 0; i--) {
            size_t j = rnd() % (i + 1);
            PackedPos t = data[i];
            data[i] = data[j];
            data[j] = t;
        }
    }
    fprintf(stderr, "zapisano %s\n", out_path);
    return 0;
}
