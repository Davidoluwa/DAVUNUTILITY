/* Every look Create Your Player can send (tests/creator_values.lua) through the real database writer on a
   fifa_ng_db.db in memory: none may be refused, and every CRC must still be right after all of them.
   build: gcc -DF16_HOST -Isrc -o test_pro_values tests-f16service/test_pro_values.c src/f16_pro.c src/f16_store.c
   usage: lua5.1 tests/creator_values.lua <ux> | ./test_pro_values <fifa_ng_db.db> <body id> */
#include "preview_platform.h"
#include "f16_pro.h"
int main(int argc, char **argv) {
    FILE *f = fopen(argv[1], "rb"); fseek(f, 0, SEEK_END); long z = ftell(f); fseek(f, 0, SEEK_SET);
    u8 *db = malloc(z); if (fread(db, 1, z, f) != (size_t)z) return 2; fclose(f);
    s32 pid = atoi(argv[2]); char line[2048], why[200]; int lines = 0, bad = 0;
    while (fgets(line, sizeof line, stdin)) {
        char *sp = strchr(line, ' '); if (!sp) continue; *sp = 0; char *p = sp + 1; p[strcspn(p, "\r\n")] = 0;
        int fi[F16_PRO_NFIELDS]; s32 v[F16_PRO_NFIELDS]; int n = 0;
        for (char *t = strtok(p, ","); t && n < F16_PRO_NFIELDS; t = strtok(0, ",")) {
            char *e = strchr(t, '='); if (!e) continue;
            fi[n] = f16_pro_field(t, (unsigned)(e - t)); v[n] = atoi(e + 1);
            if (fi[n] < 0) { printf("unknown field in %s\n", line); bad++; }
            n++;
        }
        lines++;
        if (f16_pro_db_set(db, (u32)z, pid, fi, v, n, why, sizeof why) < 0) { bad++; printf("REFUSED %s: %s\n", line, why); }
    }
    printf("%d looks, %d refused; CRCs %s\n", lines, bad, f16_pro_db_check(db, (u32)z, why, sizeof why) == 0 ? "valid" : why);
    return bad ? 1 : 0;
}
