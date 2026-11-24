/* Transcribe mono 16 kHz little-endian float32 PCM through the delivered C ABI. */
#define _POSIX_C_SOURCE 200809L
#include "audio8_asr.h"
#include <errno.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static volatile sig_atomic_t interrupted = 0;

static void request_stop(int signum) {
    interrupted = signum;
}

static int drain(a8_engine *engine, FILE *transcript) {
    a8_token tokens[64];
    int count;
    while ((count = a8_read_tokens(engine, tokens, 64)) > 0) {
        for (int i = 0; i < count; ++i) {
            fprintf(stderr, "TOKEN %d\n", tokens[i].id);
            int size = a8_token_bytes(engine, tokens[i].id, NULL, 0);
            if (size < 0) return size;
            if (size == 0) continue;
            char *bytes = malloc((size_t)size);
            if (bytes == NULL) return A8_ERR_INTERNAL;
            int written = a8_token_bytes(engine, tokens[i].id, bytes, size);
            if (written != size) {
                free(bytes);
                return written < 0 ? written : A8_ERR_INTERNAL;
            }
            size_t sent = fwrite(bytes, 1, (size_t)size, transcript);
            free(bytes);
            if (sent != (size_t)size) return A8_ERR_INTERNAL;
        }
    }
    return count;
}

int main(int argc, char **argv) {
    if (argc != 5 && argc != 6) {
        fprintf(stderr, "Usage: %s MODEL_ROOT INPUT.f32 CLOCK_MS zh|en [TRANSCRIPT_FILE]\n", argv[0]);
        return 2;
    }
    char *end = NULL;
    errno = 0;
    long clock = strtol(argv[3], &end, 10);
    if (errno || !argv[3][0] || *end || (clock != 80 && clock != 160) ||
        (strcmp(argv[4], "zh") && strcmp(argv[4], "en"))) {
        fprintf(stderr, "CLOCK_MS must be 80 or 160 and language zh or en\n");
        return 2;
    }
    const unsigned short endian = 1;
    if (*(const unsigned char *)&endian != 1 || sizeof(float) != 4) {
        fprintf(stderr, "This example requires little-endian IEEE float32\n");
        return 2;
    }
    FILE *input = fopen(argv[2], "rb");
    if (!input) { perror("input"); return 2; }
    if (fseek(input, 0, SEEK_END) != 0) { fclose(input); return 2; }
    long bytes = ftell(input);
    if (bytes <= 0 || bytes % 4 || fseek(input, 0, SEEK_SET) != 0) {
        fprintf(stderr, "Input must contain a positive whole number of float32 samples\n");
        fclose(input);
        return 2;
    }
    struct sigaction action = {0};
    action.sa_handler = request_stop;
    action.sa_flags = SA_RESTART;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) < 0 || sigaction(SIGTERM, &action, NULL) < 0) {
        fclose(input);
        return 2;
    }
    FILE *transcript = argc == 6 ? fopen(argv[5], "wb") : stdout;
    if (transcript == NULL) { perror("transcript file"); fclose(input); return 2; }
    a8_options options;
    a8_default_options(&options);
    options.clock_ms = (int)clock;
    options.lang = strcmp(argv[4], "en") == 0 ? A8_LANG_EN : A8_LANG_ZH;
    a8_engine *engine = NULL;
    int result = 1;
    engine = a8_create(argv[1], &options);
    if (engine == NULL) {
        fprintf(stderr, "%s\n", a8_create_error());
        goto done;
    }
    if (interrupted) goto done;
    if (a8_begin_request(engine, options.lang, 0) < 0) goto failed;
    if (transcript == stdout) printf("TRANSCRIPT\n");
    float pcm[3200];
    size_t samples;
    while (!interrupted && (samples = fread(pcm, sizeof(float), 3200, input)) > 0) {
        for (size_t i = 0; i < samples; ++i) {
            if (!isfinite(pcm[i])) {
                fprintf(stderr, "Input samples must be finite\n");
                goto done;
            }
        }
        if (a8_feed(engine, pcm, (int)samples) < 0 || drain(engine, transcript) < 0) goto failed;
    }
    if (interrupted) goto done;
    if (ferror(input)) { perror("input read"); goto done; }
    if (a8_finish(engine, -1) < 0 || drain(engine, transcript) < 0) goto failed;
    if (transcript == stdout && putchar('\n') == EOF) goto done;
    if (fflush(transcript) != 0) goto done;
    result = 0;
    goto done;
failed:
    fprintf(stderr, "%s\n", a8_last_error(engine));
done:
    /* All synchronous calls have returned before releasing their owners. */
    if (a8_destroy_owned(&engine) < 0) result = 1;
    if (transcript != stdout && fclose(transcript) != 0) result = 1;
    fclose(input);
    return interrupted ? 128 + interrupted : result;
}
