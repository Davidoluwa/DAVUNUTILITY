/* Host test for f16_pro (Player Career): the database patcher on a real fifa_ng_db.db, the pro: router on a copy of
   the file, and the preview override. usage: test_pro_host <fifa_ng_db.db> <scratch dir> <player id with a name row> */
#include "preview_platform.h"
#include "f16_pro.h"
#include "f16_store.h"

static int fails = 0, passes = 0;
#define CK(c, ...) do { if (c) passes++; else { fails++; printf("  FAIL  "); printf(__VA_ARGS__); printf("\n"); } } while (0)

static u8 *slurp(const char *p, u32 *n) {
    FILE *f = fopen(p, "rb"); if (!f) return 0;
    fseek(f, 0, SEEK_END); long z = ftell(f); fseek(f, 0, SEEK_SET);
    u8 *b = (u8 *)malloc((size_t)z); if (fread(b, 1, (size_t)z, f) != (size_t)z) { fclose(f); free(b); return 0; }
    fclose(f); *n = (u32)z; return b;
}
static char g_reply[4096];
static void rep(void *ctx, const char *s, unsigned int n) { (void)ctx; if (n >= sizeof(g_reply)) n = sizeof(g_reply) - 1; memcpy(g_reply, s, n); g_reply[n] = 0; }
static const char *cmd(const char *c) { f16_pro_cmd(0, 0, c, rep, 0); return g_reply; }
static int has(const char *hay, const char *needle) { return strstr(hay, needle) != 0; }
static u32 diffs(const u8 *a, const u8 *b, u32 n) { u32 d = 0; for (u32 i = 0; i < n; i++) if (a[i] != b[i]) d++; return d; }

int main(int argc, char **argv) {
    if (argc < 4) { printf("usage: %s <db> <dir> <pid>\n", argv[0]); return 2; }
    u32 n = 0; u8 *db = slurp(argv[1], &n);
    s32 pid = atoi(argv[3]);
    char why[200], out[2048];
    CK(db && n > 1000000, "the database loads (%u bytes)", n);
    if (!db) return 1;

    printf("== the image: check, set, get, refuse ==\n");
    CK(f16_pro_db_check(db, n, why, sizeof why) == 0, "every table this writer touches has the CRC it knows (%s)", why);
    u8 *orig = (u8 *)malloc(n); memcpy(orig, db, n);
    CK(f16_pro_db_get(db, n, pid, out, sizeof out) == 0, "get: %s", out);
    printf("    before: %s\n", out);
    int f[6] = { f16_pro_field("hashighqualityhead", 18), f16_pro_field("headtypecode", 12), f16_pro_field("headclasscode", 13),
                 f16_pro_field("skintonecode", 12), f16_pro_field("height", 6), f16_pro_field("weight", 6) };
    s32 v[6] = { 0, 2004, 1, 9, 191, 84 };
    for (int i = 0; i < 6; i++) CK(f[i] >= 0, "field %d known", i);
    int r = f16_pro_db_set(db, n, pid, f, v, 6, why, sizeof why);
    CK(r >= 1, "set changes the row (%d) %s", r, why);
    CK(f16_pro_db_check(db, n, why, sizeof why) == 0, "the players table's CRC is right after the change (%s)", why);
    f16_pro_db_get(db, n, pid, out, sizeof out);
    printf("    after:  %s\n", out);
    CK(has(out, "hashighqualityhead=0") && has(out, "headtypecode=2004") && has(out, "headclasscode=1") && has(out, "skintonecode=9")
       && has(out, "height=191") && has(out, "weight=84"), "the values read back");
    u32 d = diffs(orig, db, n);
    CK(d >= 1 && d <= 4 + 16, "only his row and the CRC changed (%u bytes)", d);
    CK(f16_pro_db_set(db, n, pid, f, v, 6, why, sizeof why) == 0, "the same values again change nothing");
    u8 *before = (u8 *)malloc(n); memcpy(before, db, n);
    s32 bad[2] = { 216, 90 }; int bf[2] = { f16_pro_field("height", 6), f16_pro_field("weight", 6) };
    CK(f16_pro_db_set(db, n, pid, bf, bad, 2, why, sizeof why) < 0 && has(why, "height"), "height 216 is refused: %s", why);
    CK(diffs(before, db, n) == 0, "a refused change leaves every byte as it was");
    s32 low[1] = { 149 };
    CK(f16_pro_db_set(db, n, pid, bf, low, 1, why, sizeof why) < 0, "height 149 is refused");
    CK(f16_pro_db_set(db, n, 999999, f, v, 1, why, sizeof why) < 0 && has(why, "not in"), "an unknown player is refused: %s", why);
    CK(f16_pro_field("nosuchfield", 11) < 0, "an unknown field name is refused");

    printf("== names ==\n");
    const char *nm[4] = { "Davun", "Oluwa", "D. Oluwa", "Oluwa" };
    r = f16_pro_db_name(db, n, pid, nm, why, sizeof why);
    CK(r == 1, "the name row changes (%d) %s", r, why);
    CK(f16_pro_db_check(db, n, why, sizeof why) == 0, "the editedplayernames CRC is right after the change (%s)", why);
    f16_pro_db_get(db, n, pid, out, sizeof out);
    CK(has(out, ";Davun|Oluwa|D. Oluwa|Oluwa"), "names read back: %s", strchr(out, ';'));
    CK(f16_pro_db_name(db, n, pid, nm, why, sizeof why) == 0, "the same names again change nothing");
    const char *longn[4] = { "Abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuv", "x", "x", "x" };
    memcpy(before, db, n);
    CK(f16_pro_db_name(db, n, pid, longn, why, sizeof why) < 0, "a 48-character name is refused: %s", why);
    const char *pipe[4] = { "a|b", "x", "x", "x" };
    CK(f16_pro_db_name(db, n, pid, pipe, why, sizeof why) < 0, "a name with | is refused");
    CK(diffs(before, db, n) == 0, "refused names leave every byte as it was");
    CK(f16_pro_db_name(db, n, 999999, nm, why, sizeof why) == -2, "a player without a name row: %s", why);

    printf("== the router on a copy of the file ==\n");
    char path[600], bak[640];
    snprintf(path, sizeof path, "%s/fifa_ng_db.db", argv[2]);
    snprintf(bak, sizeof bak, "%s.pro-original.bak", path);
    unlink(bak);
    CK(f16_store_write_verified(path, orig, n), "the copy is written");
    f16_pro_set_db_path(path);
    CK(!strcmp(cmd("pro:caps"), "pro:1"), "caps");
    char c[400];
    snprintf(c, sizeof c, "pro:db:%d:hashighqualityhead=0,headtypecode=2004,headclasscode=1,eyecolorcode=4,hairtypecode=16,height=188", pid);
    CK(has(cmd(c), "ok:changed="), "pro:db: %s", g_reply);
    u32 bn = 0; u8 *bk = slurp(bak, &bn);
    CK(bk && bn == n && diffs(bk, orig, n) == 0, "the original is kept once, byte for byte");
    CK(!strcmp(cmd(c), "ok:same"), "the same command again: %s", g_reply);
    snprintf(c, sizeof c, "pro:name:%d:Davun|Oluwa|D. Oluwa|Oluwa", pid);
    CK(!strcmp(cmd(c), "ok:changed"), "pro:name: %s", g_reply);
    snprintf(c, sizeof c, "pro:get:%d", pid);
    cmd(c);
    CK(has(g_reply, "headtypecode=2004") && has(g_reply, "eyecolorcode=4") && has(g_reply, "height=188") && has(g_reply, ";Davun|Oluwa|D. Oluwa|Oluwa"), "pro:get: %s", g_reply);
    u32 fn = 0; u8 *fb = slurp(path, &fn);
    CK(fb && fn == n && f16_pro_db_check(fb, fn, why, sizeof why) == 0, "the file on disk has valid CRCs");
    /* a second edit keeps the first original */
    snprintf(c, sizeof c, "pro:db:%d:height=170", pid);
    cmd(c);
    free(bk); bk = slurp(bak, &bn);
    CK(bk && diffs(bk, orig, n) == 0, "the backup is still the original after a second change");
    CK(has(cmd("pro:db:1:height=500"), "err:"), "a bad command answers err: %s", g_reply);
    CK(has(cmd("pro:db:abc:height=170"), "err:bad playerid"), "a bad player id");
    CK(has(cmd("pro:db:5:nosuch=1"), "err:unknown field"), "unknown field: %s", g_reply);
    CK(has(cmd("pro:name:5:only|three|parts"), "err:"), "a name needs four parts: %s", g_reply);
    f16_pro_set_db_path("/nonexistent/fifa_ng_db.db");
    CK(has(cmd(c), "err:no database file"), "no file: %s", g_reply);

    printf("== the preview override ==\n");
    F16ResolvedPlayer rp; memset(&rp, 0, sizeof rp); rp.hasHighQualityHead = 1; rp.headType = 7; rp.hairType = 3;
    CK(f16_pro_apply(pid, &rp) == 0 && rp.headType == 7, "no override yet");
    snprintf(c, sizeof c, "pro:look:%d:hashighqualityhead=0,headtypecode=2004,headclasscode=1,eyebrowcode=2,facialhairtypecode=5,skintonecode=8,hairtypecode=44", pid);
    CK(!strcmp(cmd(c), "ok:7"), "pro:look: %s", g_reply);
    CK(f16_pro_apply(pid, &rp) == 1 && rp.hasHighQualityHead == 0 && rp.headType == 2004 && rp.headClass == 1 && rp.eyebrow == 2 &&
       rp.facialHairType == 5 && rp.skinTone == 8 && rp.hairType == 44, "the override applies");
    F16ResolvedPlayer other; memset(&other, 0, sizeof other); other.headType = 9;
    CK(f16_pro_apply(pid + 1, &other) == 0 && other.headType == 9, "other players are untouched");
    snprintf(c, sizeof c, "pro:look:%d:clear", pid);
    cmd(c);
    memset(&rp, 0, sizeof rp); rp.headType = 7;
    CK(f16_pro_apply(pid, &rp) == 0 && rp.headType == 7, "clear removes it");
    CK(has(cmd("pro:look:5:height=x"), "err:"), "a bad look value");

    printf("%d passed, %d failed\n", passes, fails);
    return fails ? 1 : 0;
}
