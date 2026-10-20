/* pnhost.c - runs Prism Native on the PC against a real GLES2 implementation (Chromium's ANGLE on
 * SwiftShader), so the renderer is tested with the same C and shaders that run on the phone.
 *
 *   pnhost <script> [--angle DIR] [--size WxH]
 * script lines:
 *   roots <dir;dir>          asset search roots
 *   cmd <text>               pn_command("ui:" + text)   (e.g. "cmd load:/flows/prism/screens/X/X.pn")
 *   vals <name=tval|...>     binding values, '|' separates records (turned into \x1f)
 *   bg <kind>                what the "game" drew before the UI: grid | photo | black
 *   frames <n> <dt>          render n frames dt seconds apart
 *   touch <phase> <x> <y>    raw pointer event in surface px (0 down 1 move 2 up)
 *   poll                     pn_command("ui:poll") and print the reply
 *   shot <file.ppm>          read the framebuffer
 *   stats                    print quads / draw calls
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/stat.h>
#include "../src/prism/pn.h"
#include "../src/prism/pn_int.h"
static int host_head_image(pn_s32 id, pn_u8 **rgba, pn_u32 *w, pn_u32 *h);

typedef void *EGLDisplay, *EGLConfig, *EGLSurface, *EGLContext; typedef int EGLint; typedef unsigned EGLBoolean;
#define EGL_NONE 0x3038
#define EGL_SURFACE_TYPE 0x3033
#define EGL_PBUFFER_BIT 0x0001
#define EGL_RENDERABLE_TYPE 0x3040
#define EGL_OPENGL_ES2_BIT 0x0004
#define EGL_RED_SIZE 0x3024
#define EGL_GREEN_SIZE 0x3023
#define EGL_BLUE_SIZE 0x3022
#define EGL_ALPHA_SIZE 0x3021
#define EGL_WIDTH 0x3057
#define EGL_HEIGHT 0x3056
#define EGL_CONTEXT_CLIENT_VERSION 0x3098
#define EGL_PLATFORM_ANGLE_ANGLE 0x3202
#define EGL_PLATFORM_ANGLE_TYPE_ANGLE 0x3203
#define EGL_PLATFORM_ANGLE_TYPE_VULKAN_ANGLE 0x3450
#define EGL_PLATFORM_ANGLE_DEVICE_TYPE_ANGLE 0x3209
#define EGL_PLATFORM_ANGLE_DEVICE_TYPE_SWIFTSHADER_ANGLE 0x3487

static double t_now = 0;
static double host_now(void) { return t_now; }
static void *host_alloc(pn_size n) { return malloc(n); }
static void host_release(void *p) { free(p); }
static int host_read(const char *path, pn_u8 **d, pn_u32 *n) {
    FILE *f = fopen(path, "rb"); if (!f) return 0;
    fseek(f, 0, SEEK_END); long L = ftell(f); fseek(f, 0, SEEK_SET);
    if (L < 0) { fclose(f); return 0; }
    *d = malloc(L ? L : 1); *n = (pn_u32)fread(*d, 1, L, f); fclose(f); return 1;
}
static int host_read_part(const char *path, pn_u32 off, pn_u32 len, pn_u8 *out, pn_u32 *fs) {
    FILE *f = fopen(path, "rb"); if (!f) return 0;
    fseek(f, 0, SEEK_END); long L = ftell(f); if (fs) *fs = (pn_u32)L;
    if (len) { fseek(f, off, SEEK_SET); if (fread(out, 1, len, f) != len) { fclose(f); return 0; } }
    fclose(f); return 1;
}
/* a stand-in for the game's OBB (tests): PN_FAKE_OBB names a BIG4 file; its entries are the "logical" files, an entry
   ending in ".big" is a BIG4 archive nested in it */
typedef struct { char name[160]; unsigned off, size; } FakeEnt;
static FakeEnt *fakeEnts; static unsigned nfake; static char fakePath[400]; static int fakeLoaded;
static unsigned be32h(const unsigned char *p) { return ((unsigned)p[0] << 24) | ((unsigned)p[1] << 16) | ((unsigned)p[2] << 8) | p[3]; }
static void fake_load(void) {
    if (fakeLoaded) return; fakeLoaded = 1;
    const char *p = getenv("PN_FAKE_OBB"); if (!p) return;
    snprintf(fakePath, sizeof fakePath, "%s", p);
    FILE *f = fopen(p, "rb"); if (!f) return;
    unsigned char h[16]; if (fread(h, 1, 16, f) != 16 || memcmp(h, "BIG4", 4)) { fclose(f); return; }
    unsigned n = be32h(h + 8); fakeEnts = calloc(n, sizeof(FakeEnt));
    for (unsigned i = 0; i < n; i++) {
        unsigned char e[8]; if (fread(e, 1, 8, f) != 8) break;
        fakeEnts[i].off = be32h(e); fakeEnts[i].size = be32h(e + 4);
        int c, k = 0; while ((c = fgetc(f)) > 0) if (k < 159) fakeEnts[i].name[k++] = (char)c;
        nfake++;
    }
    fclose(f);
}
static int fake_find(const char *logical) { fake_load(); for (unsigned i = 0; i < nfake; i++) if (!strcasecmp(fakeEnts[i].name, logical)) return (int)i; return -1; }
static int host_locate_logical(const char *l, char *path, pn_u32 cap, pn_u32 *off, pn_u32 *size) { int i = fake_find(l); if (i < 0) return 0; snprintf(path, cap, "%s", fakePath); if (off) *off = fakeEnts[i].off; if (size) *size = fakeEnts[i].size; return 1; }
static int host_read_logical(const char *l, pn_u8 **d, pn_u32 *n) {
    int i = fake_find(l); if (i < 0) return 0;
    FILE *f = fopen(fakePath, "rb"); if (!f) return 0; fseek(f, fakeEnts[i].off, SEEK_SET);
    *d = malloc(fakeEnts[i].size ? fakeEnts[i].size : 1); *n = (pn_u32)fread(*d, 1, fakeEnts[i].size, f); fclose(f); return 1;
}
static int host_nth_logical(const char *sfx, pn_u32 n, char *out, pn_u32 cap) {
    fake_load(); pn_u32 k = 0, ls = (pn_u32)strlen(sfx);
    for (unsigned i = 0; i < nfake; i++) { pn_u32 ln = (pn_u32)strlen(fakeEnts[i].name); if (ln >= ls && !strcasecmp(fakeEnts[i].name + ln - ls, sfx)) { if (k == n) { snprintf(out, cap, "%s", fakeEnts[i].name); return 1; } k++; } }
    return 0;
}
static int host_find_logical(const char *prefix, const char *contains, char *out, pn_u32 cap) {
    fake_load(); for (unsigned i = 0; i < nfake; i++) if (strcasestr(fakeEnts[i].name, contains)) { snprintf(out, cap, "%s", fakeEnts[i].name); return 1; } return 0;
}
static void host_log(int lvl, const char *m) { fprintf(stderr, "[%s] %s\n", lvl == 0 ? "I" : lvl == 1 ? "W" : "E", m); }
static int libMode = 0;
static void host_reply(const char *k, const char *v) {
    if (libMode) { setenv(k, v, 1); return; }
    printf("REPLY %s=", k);
    for (const char *p = v; *p; p++) { if (*p == '\x1e') printf(" | "); else if (*p == '\x1f') printf(" ; "); else putchar(*p); }
    printf("\n"); fflush(stdout);
}

static void *G;
static void *sym(const char *n) { void *p = dlsym(G, n); if (!p) { fprintf(stderr, "missing GL symbol %s\n", n); exit(2); } return p; }
#define L(field, name) pn_gl.field = sym(name)

static int W = 2340, H = 1080;
static void (*gClearColor)(float, float, float, float); static void (*gClear)(unsigned); static void (*gScissor)(int, int, int, int);
static void (*gEnable)(unsigned); static void (*gDisable)(unsigned); static void (*gReadPixels)(int, int, int, int, unsigned, unsigned, void *);
static void (*gViewport)(int, int, int, int); static void (*gFinish)(void);
static char bgKind[32] = "grid";

/* the "game frame": something with detail so glass blur and alpha are visible */
static void draw_background(void) {
    gViewport(0, 0, W, H); gDisable(0x0C11);
    if (!strcmp(bgKind, "black")) { gClearColor(0, 0, 0, 1); gClear(0x4000); return; }
    gClearColor(0.10f, 0.12f, 0.16f, 1); gClear(0x4000);
    gEnable(0x0C11);
    if (!strcmp(bgKind, "grid")) {
        for (int y = 0; y < H; y += 60) for (int x = 0; x < W; x += 60) {
            int c = ((x / 60) + (y / 60)) & 1; gScissor(x, y, 60, 60);
            gClearColor(c ? 0.20f : 0.13f, c ? 0.24f : 0.15f, c ? 0.30f : 0.19f, 1); gClear(0x4000);
        }
    } else { /* "photo": big soft colour blocks like a stadium shot */
        float cols[6][3] = {{0.05f, 0.35f, 0.18f}, {0.08f, 0.45f, 0.22f}, {0.70f, 0.72f, 0.75f}, {0.12f, 0.15f, 0.40f}, {0.85f, 0.30f, 0.20f}, {0.95f, 0.85f, 0.30f}};
        for (int i = 0; i < 40; i++) { int x = (i * 397) % W, y = (i * 211) % H, w = 120 + (i * 53) % 400, h = 80 + (i * 37) % 300; float *c = cols[i % 6]; gScissor(x, y, w, h); gClearColor(c[0], c[1], c[2], 1); gClear(0x4000); }
    }
    gDisable(0x0C11);
}
static int slotDrawn[8];
static void draw_slot(int slot, float x, float y, float scale, float tw, float th) {
    /* stand-in for the 3D model: a capsule-ish block where libpv would draw the player */
    float hpx = 0.86f * scale * H, wpx = hpx * 0.38f; float cx = (x * 0.5f + 0.5f) * W, cy = (0.5f - y * 0.5f) * H;
    gEnable(0x0C11); gScissor((int)(cx - wpx / 2), (int)(H - (cy + hpx / 2)), (int)wpx, (int)hpx);
    gClearColor(0.30f, 0.27f, 0.34f, 1); gClear(0x4000); gDisable(0x0C11);
    slotDrawn[slot & 7]++;
    (void)tw; (void)th;
}
static void shot(const char *file) {
    unsigned char *px = malloc((size_t)W * H * 4);
    gReadPixels(0, 0, W, H, 0x1908, 0x1401, px);
    FILE *f = fopen(file, "wb"); fprintf(f, "P6\n%d %d\n255\n", W, H);
    for (int y = H - 1; y >= 0; y--) for (int x = 0; x < W; x++) fwrite(px + ((size_t)y * W + x) * 4, 1, 3, f);
    fclose(f); free(px);
    printf("SHOT %s\n", file);
}

static unsigned (*gErr)(void);
static int gl_init(const char *angle) {
    char p[600];
    snprintf(p, sizeof p, "%s/libEGL.so", angle); void *E = dlopen(p, RTLD_NOW | RTLD_GLOBAL);
    snprintf(p, sizeof p, "%s/libGLESv2.so", angle); G = dlopen(p, RTLD_NOW | RTLD_GLOBAL);
    if (!E || !G) { fprintf(stderr, "cannot load ANGLE: %s\n", dlerror()); return 2; }
    EGLDisplay (*getPlat)(unsigned, void *, const EGLint *) = dlsym(E, "eglGetPlatformDisplayEXT");
    EGLBoolean (*init)(EGLDisplay, EGLint *, EGLint *) = dlsym(E, "eglInitialize");
    EGLBoolean (*choose)(EGLDisplay, const EGLint *, EGLConfig *, EGLint, EGLint *) = dlsym(E, "eglChooseConfig");
    EGLSurface (*pbuf)(EGLDisplay, EGLConfig, const EGLint *) = dlsym(E, "eglCreatePbufferSurface");
    EGLContext (*ctx)(EGLDisplay, EGLConfig, EGLContext, const EGLint *) = dlsym(E, "eglCreateContext");
    EGLBoolean (*make)(EGLDisplay, EGLSurface, EGLSurface, EGLContext) = dlsym(E, "eglMakeCurrent");
    EGLint pa[] = {EGL_PLATFORM_ANGLE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_TYPE_VULKAN_ANGLE, EGL_PLATFORM_ANGLE_DEVICE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_DEVICE_TYPE_SWIFTSHADER_ANGLE, EGL_NONE};
    EGLDisplay d = getPlat(EGL_PLATFORM_ANGLE_ANGLE, (void *)0, pa); EGLint ma, mi;
    if (!d || !init(d, &ma, &mi)) { fprintf(stderr, "eglInitialize failed\n"); return 3; }
    EGLint ca[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
    EGLConfig cfg; EGLint n = 0; choose(d, ca, &cfg, 1, &n); if (!n) { fprintf(stderr, "no config\n"); return 3; }
    EGLint sa[] = {EGL_WIDTH, W, EGL_HEIGHT, H, EGL_NONE}; EGLSurface s = pbuf(d, cfg, sa);
    EGLint xa[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE}; EGLContext c = ctx(d, cfg, 0, xa);
    if (!s || !c || !make(d, s, s, c)) { fprintf(stderr, "context failed\n"); return 3; }
    const unsigned char *(*gs)(unsigned) = sym("glGetString");
    fprintf(stderr, "GL: %s | %s\n", gs(0x1F01), gs(0x1F02));

    L(ActiveTexture, "glActiveTexture"); L(AttachShader, "glAttachShader"); L(BindAttribLocation, "glBindAttribLocation"); L(BindBuffer, "glBindBuffer");
    L(BindFramebuffer, "glBindFramebuffer"); L(BindTexture, "glBindTexture"); L(BlendFuncSeparate, "glBlendFuncSeparate"); L(BufferData, "glBufferData");
    L(BufferSubData, "glBufferSubData"); L(CheckFramebufferStatus, "glCheckFramebufferStatus"); L(Clear, "glClear"); L(ClearColor, "glClearColor");
    L(CompileShader, "glCompileShader"); L(CopyTexSubImage2D, "glCopyTexSubImage2D"); L(CreateProgram, "glCreateProgram"); L(CreateShader, "glCreateShader");
    L(DeleteBuffers, "glDeleteBuffers"); L(DeleteFramebuffers, "glDeleteFramebuffers"); L(DeleteProgram, "glDeleteProgram"); L(DeleteShader, "glDeleteShader");
    L(DeleteTextures, "glDeleteTextures"); L(Disable, "glDisable"); L(DisableVertexAttribArray, "glDisableVertexAttribArray"); L(DrawElements, "glDrawElements");
    L(Enable, "glEnable"); L(EnableVertexAttribArray, "glEnableVertexAttribArray"); L(FramebufferTexture2D, "glFramebufferTexture2D"); L(GenBuffers, "glGenBuffers");
    L(GenFramebuffers, "glGenFramebuffers"); L(GenTextures, "glGenTextures"); L(GetBooleanv, "glGetBooleanv"); L(GetIntegerv, "glGetIntegerv");
    L(GetProgramiv, "glGetProgramiv"); L(GetProgramInfoLog, "glGetProgramInfoLog"); L(GetShaderiv, "glGetShaderiv"); L(GetShaderInfoLog, "glGetShaderInfoLog");
    L(GetUniformLocation, "glGetUniformLocation"); L(GetVertexAttribiv, "glGetVertexAttribiv"); L(IsEnabled, "glIsEnabled"); L(LinkProgram, "glLinkProgram");
    L(PixelStorei, "glPixelStorei"); L(Scissor, "glScissor"); L(ShaderSource, "glShaderSource"); L(TexImage2D, "glTexImage2D"); L(TexParameteri, "glTexParameteri");
    L(TexSubImage2D, "glTexSubImage2D"); L(Uniform1f, "glUniform1f"); L(Uniform1i, "glUniform1i"); L(Uniform2f, "glUniform2f"); L(Uniform4f, "glUniform4f");
    L(Uniform2fv, "glUniform2fv"); L(UseProgram, "glUseProgram"); L(VertexAttribPointer, "glVertexAttribPointer"); L(Viewport, "glViewport"); L(ColorMask, "glColorMask");
    if (!getenv("PN_NO_VAO")) { pn_gl.BindVertexArrayOES = dlsym(G, "glBindVertexArrayOES"); pn_gl.GenVertexArraysOES = dlsym(G, "glGenVertexArraysOES"); pn_gl.DeleteVertexArraysOES = dlsym(G, "glDeleteVertexArraysOES"); }
    gClearColor = sym("glClearColor"); gClear = sym("glClear"); gScissor = sym("glScissor"); gEnable = sym("glEnable"); gDisable = sym("glDisable");
    gReadPixels = sym("glReadPixels"); gViewport = sym("glViewport"); gFinish = sym("glFinish");
    gErr = sym("glGetError");
    pn_host.alloc = host_alloc; pn_host.release = host_release; pn_host.read_file = host_read; pn_host.read_part = host_read_part;
    pn_host.log = host_log; pn_host.reply = host_reply; pn_host.now = host_now;
    if (getenv("PN_FAKE_HEADS")) pn_host.head_image = host_head_image;
    if (getenv("PN_FAKE_OBB")) { pn_host.read_logical = host_read_logical; pn_host.locate_logical = host_locate_logical; pn_host.nth_logical = host_nth_logical; pn_host.find_logical = host_find_logical; }
    return 0;
}

/* ---- library entry points (tests drive Prism.lua against the real native code through ctypes) */
extern PnState pn_s;
int pnt_init(int w, int h, const char *roots) { W = w; H = h; libMode = 1; int r = gl_init("/opt/pw-browsers/chromium-1194/chrome-linux"); if (roots) pn_set_roots(roots); pn_s.touchOk = 1; return r; }
int pnt_command(const char *cmd) { return pn_command(cmd); }
void pnt_frames(int n, double dt) { for (int i = 0; i < n; i++) { t_now += dt; draw_background(); pn_frame(W, H, t_now, draw_slot); } }
const char *pnt_reply(void) { return pn_last_reply(""); }
int pnt_touch(int phase, float x, float y) { return pn_touch(phase, x, y); }
void pnt_shot(const char *file) { gFinish(); shot(file); }
unsigned pnt_gl_error(void) { return gErr(); }
void pnt_set_touch(int v) { pn_s.touchOk = v; }
double pnt_time(void) { return t_now; }
void pnt_advance(double dt) { t_now += dt; }
/* tests: resolve and load one asset path through the real texture table; returns the slot state (2 = ready, 3 = failed) */

/* PN_FAKE_HEADS=n: libpv's 3D head pictures, played by the harness: player id 7xxx has none, every other id is
   "being made" for the first n asks and then a 128x128 picture (a disc whose grey level is id % 256) */
static int g_headAsks;
static int host_head_image(pn_s32 id, pn_u8 **rgba, pn_u32 *w, pn_u32 *h) {
    if (id >= 7000 && id < 8000) return -1;
    if (g_headAsks++ < atoi(getenv("PN_FAKE_HEADS"))) return 0;
    pn_u8 *p = (pn_u8 *)malloc(128 * 128 * 4); if (!p) return -1;
    for (int y = 0; y < 128; y++) for (int x = 0; x < 128; x++) { int dx = x - 64, dy = y - 60, in = dx * dx + dy * dy < 50 * 50; pn_u8 *q = p + (y * 128 + x) * 4; q[0] = q[1] = q[2] = in ? (pn_u8)(id % 256) : 0; q[3] = in ? 255 : 0; }
    *rgba = p; *w = 128; *h = 128; return 1;
}
int pnt_head_asks(void) { return g_headAsks; }
int pnt_tex_state(const char *path) { int ti = pn_tex_find(path); return ti < 0 ? -1 : pn_s.texs[ti].state; }
int pnt_tex_step(const char *path) { int ti = pn_tex_find(path); if (ti < 0) return -1; pn_s.texs[ti].lastUse = pn_s.frames; return pn_tex_load_step(ti); }
int pnt_tex_waiting(void) { return pn_tex_waiting(); }

int pnt_asset_probe(const char *path, int *w, int *h, unsigned *gen) {
    int ti = pn_tex_find(path); if (ti < 0) return -1;
    for (int i = 0; i < 3; i++) pn_tex_load_step(ti);
    PnTex *t = &pn_s.texs[ti]; if (w) *w = t->w; if (h) *h = t->h; if (gen) *gen = t->gen; return t->state;
}
unsigned pnt_tex_count(void) { return pn_s.ntex; }
/* what os.getenv("PRISM_UI_EV") returns on the phone: libpv answers the per-frame poll itself */
int pnt_poll_env(char *out, unsigned cap) { return pn_poll_env(out, cap); }
void pnt_tick(void) { pn_s.frames += 3; }
/* tests: a layer's state by id: '-' none, 'O' open, 'H' held, 'E' exiting, 'w' opened but waiting for its ready */
int pnt_layer_state(const char *id) { for (int i = 0; i < PN_MAX_LAYERS; i++) { PnLayer *L = &pn_s.layers[i]; if (L->state != L_FREE && !strcmp(L->id, id)) return L->waiting ? 'w' : "-OHE"[L->state]; } return '-'; }
/* tests: quads drawn by the last built frame */
unsigned pnt_quads(void) { return pn_s.quads; }

#ifndef PN_LIB
int main(int argc, char **argv) {
    const char *script = NULL, *angle = "/opt/pw-browsers/chromium-1194/chrome-linux";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--angle") && i + 1 < argc) angle = argv[++i];
        else if (!strcmp(argv[i], "--size") && i + 1 < argc) sscanf(argv[++i], "%dx%d", &W, &H);
        else script = argv[i];
    }
    if (!script) { fprintf(stderr, "usage: pnhost script [--size WxH]\n"); return 1; }
    if (gl_init(angle)) return 3;
    pn_s.touchOk = 1;
    FILE *sf = fopen(script, "r"); if (!sf) { perror(script); return 1; }
    char line[65536];
    while (fgets(line, sizeof line, sf)) {
        size_t L = strlen(line); while (L && (line[L - 1] == '\n' || line[L - 1] == '\r')) line[--L] = 0;
        if (!L || line[0] == '#') continue;
        char *arg = strchr(line, ' '); if (arg) *arg++ = 0; else arg = line + L;
        if (!strcmp(line, "roots")) pn_set_roots(arg);
        else if (!strcmp(line, "cmd")) { char b[70000]; snprintf(b, sizeof b, "ui:%s", arg); pn_command(b); }
        else if (!strcmp(line, "vals")) { char b[70000]; snprintf(b, sizeof b, "ui:v:%s", arg); char *q0 = strchr(b + 5, '|'); for (char *q = q0 ? q0 + 1 : b; *q; q++) if (*q == '|') *q = '\x1f'; pn_command(b); }
        else if (!strcmp(line, "bg")) snprintf(bgKind, sizeof bgKind, "%s", arg);
        else if (!strcmp(line, "frames")) {
            int k = 1; double dt = 1.0 / 60; sscanf(arg, "%d %lf", &k, &dt);
            for (int i = 0; i < k; i++) { t_now += dt; draw_background(); pn_command("ui:poll:h|*"); pn_frame(W, H, t_now, draw_slot); }
            unsigned e = gErr(); if (e) printf("GLERROR 0x%x\n", e);
        } else if (!strcmp(line, "touch")) { int ph; float x, y; sscanf(arg, "%d %f %f", &ph, &x, &y); int took = pn_touch(ph, x, y); printf("TOUCH %d %.0f %.0f took=%d\n", ph, x, y, took); }
        else if (!strcmp(line, "poll")) { pn_command("ui:poll:h|*"); printf("POLL %s\n", pn_last_reply("")); }
        else if (!strcmp(line, "rows")) { /* rows <layer>|<list>|<n>|<data>: '^' separates rows, '~' fields */
            char b[70000]; snprintf(b, sizeof b, "ui:a:%s", arg); for (char *q = b; *q; q++) { if (*q == '^') *q = '\x1e'; else if (*q == '~') *q = '\x1d'; } pn_command(b); }
        else if (!strcmp(line, "advance")) { double dt = atof(arg); t_now += dt; }
        else if (!strcmp(line, "shot")) { gFinish(); shot(arg); }
        else if (!strcmp(line, "stats")) { pn_command("ui:dump"); printf("SLOTS"); for (int i = 0; i < 8; i++) printf(" %d", slotDrawn[i]); printf(" claimed=0x%x\n", pn_claimed_slots()); }
        else if (!strcmp(line, "time")) { struct timespec a, b; int k = atoi(arg); clock_gettime(CLOCK_MONOTONIC, &a); for (int i = 0; i < k; i++) { t_now += 1.0 / 60; draw_background(); pn_command("ui:poll:h|*"); pn_frame(W, H, t_now, draw_slot); } gFinish(); clock_gettime(CLOCK_MONOTONIC, &b); printf("TIME %d frames %.2f ms/frame (SwiftShader CPU raster)\n", k, ((b.tv_sec - a.tv_sec) * 1e3 + (b.tv_nsec - a.tv_nsec) / 1e6) / k); }
        else fprintf(stderr, "unknown script line: %s\n", line);
    }
    return 0;
}
#endif
