/* pn_core.c - Prism Native 4: layers, screen transitions, theme, the Lua command protocol and the frame.
 *
 * Every Lua screen (a skinned career VVM, or a Prism screen) owns one layer. Opening a layer while another one at
 * the same z is being left pairs them: the old screen stays on screen (held) until the new one exists, then both
 * animate (push / back / fade / rise). The shell layer (shared career background) persists across screens. */
#include "pn_int.h"

PnHost pn_host;
PnGL pn_gl;
PnState pn_s;

void pn_logf(int level, const char *a, const char *b, const char *c) {
    char buf[600]; PnStr sb; pn_sb_init(&sb, buf, sizeof(buf));
    pn_sb_add(&sb, "prism: "); pn_sb_add(&sb, a); if (b) pn_sb_add(&sb, b); if (c) pn_sb_add(&sb, c);
    if (pn_host.log) pn_host.log(level, buf);
}
static void lock(void) { if (pn_host.lock) pn_host.lock(); }
static int g_inited;
void pn_ensure_init(void) {
    if (g_inited) return;
    g_inited = 1; pn_s.tDown = pn_s.tPan = pn_s.tList = -1; pn_s.tLayer = -1; pn_s.tRow = -1;
    pn_s.show = 1;   /* shown until Lua hides them (ui:hide while a stock screen is up); opening a screen no longer forces it */
}
static void unlock(void) { if (pn_host.unlock) pn_host.unlock(); }
static double now(void) { return pn_host.now ? pn_host.now() : 0; }

PnNode *pn_node(PnScene *sc, pn_s32 i) { return (sc && i >= 0 && (pn_u32)i < sc->nnodes) ? &sc->nodes[i] : NULL; }

void pn_queue_event(const char *a, const char *b, const char *c) {
    char buf[300]; PnStr sb; pn_sb_init(&sb, buf, sizeof(buf)); pn_sb_add(&sb, a); if (b) pn_sb_add(&sb, b); if (c) pn_sb_add(&sb, c);
    if (pn_s.evlen + sb.len + 2 >= sizeof(pn_s.events)) { pn_s.evDropped++; return; }
    if (pn_s.evlen) pn_s.events[pn_s.evlen++] = '\x1e';
    pn_memcpy(pn_s.events + pn_s.evlen, buf, sb.len); pn_s.evlen += sb.len; pn_s.events[pn_s.evlen] = 0;
}

/* ---------------------------------------------------------------- layers */
static int layer_find(const char *id) {
    for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE && pn_streq(pn_s.layers[i].id, id)) return i;
    return -1;
}
static int layer_find_n(const char *id, pn_u32 n) {
    for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE && pn_strlen(pn_s.layers[i].id) == n && pn_strneq(pn_s.layers[i].id, id, n)) return i;
    return -1;
}
static void layer_free(int i) {
    PnLayer *L = &pn_s.layers[i];
    if (L->sc) pn_scene_free(L->sc);
    pn_memset(L, 0, sizeof(*L));
    pr_layer_free(i); pn_s.tick++;
}
void pn_mark_change(void) { pn_s.tick++; }
static int layer_alloc(void) {
    for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state == L_FREE) return i;
    /* full: drop the oldest exiting/held layer */
    int best = -1; pn_u32 bo = 0xFFFFFFFFu;
    for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_OPEN && pn_s.layers[i].order < bo) { bo = pn_s.layers[i].order; best = i; }
    if (best >= 0) { layer_free(best); return best; }
    return -1;
}
static void start_exit(PnLayer *L, int preset, int dir, double t) {
    if (L->departing == 1) preset = TP_NONE;   /* it already slid out when the tap navigated away */
    L->state = L_EXIT; L->t0 = t; L->preset = (pn_u8)preset; L->dir = (pn_s8)dir;
    L->dur = L->sc ? L->sc->exitDur : 0.2f; if (preset == TP_FADE && L->dur > 0.18f && !(L->sc && L->sc->exitDur > L->sc->dur)) L->dur = 0.16f;
    if (preset == TP_NONE) L->dur = 0.001f;
    if (L->sc) pn_scene_trigger(L->sc, TR_EXIT, t);
}
/* a new layer at z pairs with a held one at the same z */
static void pair_with_held(PnLayer *N, double t) {
    PnScene *sc = N->sc;
    for (int i = 0; i < PN_MAX_LAYERS; i++) {
        PnLayer *O = &pn_s.layers[i];
        if (O == N || O->state != L_HELD || !O->sc || O->sc->z != sc->z || O->sc->shell) continue;
        int preset = N->preset == TP_PUSH ? (N->dir < 0 ? TP_BACK : TP_PUSH) : N->preset;
        start_exit(O, preset == TP_RISE ? TP_FADE : preset, N->dir, t);
    }
}

/* the layer starts its life on screen: direction, pairing with the held screen, enter motion */
static void layer_activate(PnLayer *L, int back, double tn) {
    PnScene *sc = L->sc;
    int dir = back || pn_s.dirNext < 0 ? -1 : 1;
    if (!back && pn_s.dirNext == 0 && sc->depth >= 0) {
        /* no explicit direction: a shallower screen than the one being left means "back" */
        for (int i = 0; i < PN_MAX_LAYERS; i++) { PnLayer *O = &pn_s.layers[i]; if (O != L && O->state == L_HELD && O->sc && O->sc->z == sc->z && O->sc->depth >= 0) dir = sc->depth < O->sc->depth ? -1 : 1; }
    }
    pn_s.dirNext = 0;
    L->dir = (pn_s8)dir; L->t0 = tn; L->lastPoll = tn;
    L->preset = sc->preset; if (L->preset == TP_PUSH && L->dir < 0) L->preset = TP_BACK;
    L->dur = sc->dur;
    int paired = 0; for (int i = 0; i < PN_MAX_LAYERS; i++) if (&pn_s.layers[i] != L && pn_s.layers[i].state == L_HELD && pn_s.layers[i].sc && pn_s.layers[i].sc->z == sc->z) paired = 1;
    if (!paired && (L->preset == TP_PUSH || L->preset == TP_BACK)) { L->preset = TP_FADE; L->dur = 0.18f; }
    pair_with_held(L, tn);
    pn_s.now = tn;
    pn_scene_settle(sc);
    pn_scene_trigger(sc, TR_ENTER, tn);
    /* R68: no pn_s.show = 1 here any more. A screen opening while Lua has the native screens hidden (a stock screen such
       as Settings is up) stays hidden with them: showing them made the native hub cover the open Settings, and a popup
       opened then showed twice (natively, and its stock copy that Lua had switched on) */
}

/* per-frame layer transform from its transition */
static void layer_progress(PnLayer *L, double t) {
    L->lx = 0; L->lalpha = 1; L->ls = 1;
    float d = L->dur > 0.001f ? L->dur : 0.001f, u = (float)(t - L->t0) / d;
    if (L->state == L_OPEN) {
        if (L->notrans || L->preset == TP_NONE || u >= 1.f) return;
        float e = pn_ease(EZ_OUTCUBIC, u);
        switch (L->preset) {
        case TP_PUSH: L->lx = (L->dir < 0 ? -0.04f : 0.06f) * (1.f - e); L->lalpha = pn_ease(EZ_OUTQUAD, u * 1.4f); break;
        case TP_BACK: L->lx = -0.04f * (1.f - e); L->lalpha = pn_ease(EZ_OUTQUAD, u * 1.4f); break;
        case TP_FADE: L->lalpha = e; break;
        case TP_RISE: L->ls = 0.965f + 0.035f * e; L->lalpha = pn_ease(EZ_OUTQUAD, u * 1.6f); break;
        }
    } else if (L->state == L_EXIT) {
        float e = pn_ease(EZ_INOUTQUAD, u > 1.f ? 1.f : u), sd = L->sc ? L->sc->dur : d;
        float ue = (float)(t - L->t0) / (sd > 0.001f ? sd : 0.001f); float ee = pn_ease(EZ_OUTCUBIC, ue > 1.f ? 1.f : ue);
        switch (L->preset) {
        case TP_PUSH: L->lx = (L->dir < 0 ? 0.06f : -0.03f) * ee; L->lalpha = 1.f - pn_ease(EZ_OUTQUAD, ue * 1.6f); break;
        case TP_BACK: L->lx = 0.06f * ee; L->lalpha = 1.f - pn_ease(EZ_OUTQUAD, ue * 1.6f); break;
        case TP_RISE: L->ls = 1.f - 0.03f * ee; L->lalpha = 1.f - ee; break;
        default: L->lalpha = 1.f - e; break;
        }
        if (L->lalpha < 0) L->lalpha = 0;
    }
}
/* the depart motion on top of the state's own (layer_progress returns early once an enter has played) */
static void layer_depart(PnLayer *L, double t) {
    if (L->departing && L->state != L_EXIT) {
        /* departing (R68): the screen answers the tap at once - its content slides out to the shell in 0.12 s while the
           game builds the next screen (~0.4 s of its own work), which then slides in. 2: it comes back (no successor came) */
        float u = (float)(t - L->departT0) / (L->departing == 2 ? 0.16f : 0.12f); if (u > 1.f) u = 1.f;
        float e = pn_ease(EZ_OUTCUBIC, u); if (L->departing == 2) e = 1.f - e;
        L->lalpha *= 1.f - e; L->lx += (float)L->departDir * 0.025f * e;
        if (L->departing == 2 && u >= 1.f) L->departing = 0;
    }
}

/* A layer opened with "wait" that never became ready is dropped: a screen whose open was abandoned must not keep the
   screens it replaces up (they stay while it waits). R98e: only once the game's Lua has had the time AND the frames to
   send that ready, 3 s and PN_WAIT_POLLS polls (every live screen polls once a frame; Lua's own gates end after 2 s or
   45 + 12 frames), or after 30 s whatever it does. After a match the engine keeps the Lua thread busy or stopped for
   longer than 3 s (career processing, the save): the hub and its Match Results were dropped while their ready was still
   to come, the shell went with them, and the hub's stock layout (its widgets hidden for the native screen) showed
   black until the back key left the career. */
#define PN_WAIT_POLLS 180
/* a Lua read: the heartbeat of every layer (the watchdog), and one more poll for a waiting one's deadline */
static void layer_polled(PnLayer *L, double tn) { L->lastPoll = tn; if (L->waiting && L->waitPolls < 0x7FFFFFFFu) L->waitPolls++; }

static void layers_update(double t, float dt) {
    int anyContent = 0;
    for (int i = 0; i < PN_MAX_LAYERS; i++) { PnLayer *L = &pn_s.layers[i]; if (L->state != L_FREE && L->sc && !L->sc->shell && L->state != L_EXIT) anyContent = 1; }
    int anyWaiting = 0; for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE && pn_s.layers[i].waiting) anyWaiting = 1;   /* a screen preparing to take over */
    for (int i = 0; i < PN_MAX_LAYERS; i++) {
        PnLayer *L = &pn_s.layers[i];
        if (L->state == L_FREE) continue;
        if (L->waiting) { if ((t - L->openedAt > 3.0 && L->waitPolls >= PN_WAIT_POLLS) || t - L->openedAt > 30.0) { PN_WARN("open: layer never became ready, dropped: ", L->id); layer_free(i); } continue; }
        if (L->state == L_HELD && !anyWaiting && t - L->heldAt > (L->holdFor > 0 ? L->holdFor : 0.6)) { start_exit(L, TP_FADE, 1, t); PN_LOG2("layer: leaves the screen: ", L->id); }
        if (L->state == L_EXIT && (float)(t - L->t0) >= L->dur) { layer_free(i); continue; }
        if (L->departing == 1 && L->state == L_OPEN && t - L->departT0 > 2.0) { L->departing = 2; L->departT0 = t; }
        /* watchdog: an open screen whose Lua stopped polling for 30 s fades out (it comes back when polled again).
           Every Lua read refreshes every layer, so this only fires while the WHOLE Lua thread is blocked - which is
           what the engine does while it loads (career loading blocks it for 20 s and more). The stock layout under a
           native screen has its widgets hidden, so fading then showed black: the loading screen is never faded ("keep"),
           other screens only after 30 s, as a safety net for a layer left over when the UI is gone (a match).
           The shell (the room behind the screens) goes as soon as no screen is on it, whatever polls. */
        int asleep = L->state == L_OPEN && !L->sc->shell && !L->sc->keep && (t - L->lastPoll) > 30.0;
        if (L->sc && L->sc->shell) { if (anyContent) L->noContentAt = 0; else if (L->noContentAt <= 0) L->noContentAt = t; asleep = !anyContent && (t - L->noContentAt) > 0.04; }
        float target = asleep ? 0.f : 1.f; L->wdT = target;
        if (L->wd != target) { L->wd += (target > L->wd ? 1.f : -1.f) * dt / 0.16f; L->wd = pn_clampf(L->wd, 0, 1); }
        if (L->sc && L->sc->shell && !anyContent && L->wd <= 0.f) { PN_LOG2("layer: shell removed with the last screen", ""); layer_free(i); continue; }
    }
}

/* the per-frame poll served straight from os.getenv("PRISM_UI_EV") (no console command): the same reply as
   "poll:<seq>|*" would give, the read counts as the Lua heartbeat for every open layer */
static pn_u32 g_pollSeq;
int pn_poll_env(char *out, pn_u32 cap) {
    pn_ensure_init();
    double tn = now();
    lock();
    for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE) layer_polled(&pn_s.layers[i], tn);
    int any = 0; for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state == L_OPEN) any = 1;
    int gl = pr_gl_state();
    PnStr sb; pn_sb_init(&sb, out, cap);
    pn_sb_add(&sb, "s"); pn_sb_ch(&sb, any ? '1' : '0');
    pn_sb_ch(&sb, pn_s.touchOk > 0 ? '1' : pn_s.touchOk < 0 ? 'x' : '0'); pn_sb_ch(&sb, gl > 0 ? '1' : gl < 0 ? 'x' : '0');
    pn_sb_ch(&sb, ':'); pn_sb_add(&sb, "e"); pn_sb_int(&sb, (long)++g_pollSeq);
    if (pn_s.evlen) { pn_sb_ch(&sb, '\x1e'); pn_sb_add(&sb, pn_s.events); }
    pn_s.evlen = 0; pn_s.events[0] = 0;
    unlock();
    return 1;
}

/* ---------------------------------------------------------------- frame */
void pn_set_touch_state(int state) { pn_s.touchOk = state; }
int pn_active(void) { for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE) return 1; return 0; }
pn_u32 pn_claimed_slots(void) { return pn_s.claimed; }
int pn_hidden(void) { return !pn_s.show; }   /* ui:hide (a stock overlay is up over the native screens) */

static int g_built;                /* 1: vertices built this frame, 2: idle frame, the cached pictures are reused */
static pn_u32 g_lastTick, g_sinceFull;
void pn_frame(int vw, int vh, double t, PnDrawSlotFn drawSlot) { if (pn_frame_build(vw, vh, t)) pn_frame_submit(drawSlot); }
/* anything still moving? (a transition, a watchdog fade, a timeline, a scroll, a press) */
static int layer_active(const PnLayer *L, double t) {
    if (L->state != L_OPEN || L->waiting) return 1;
    if (L->wd != L->wdT) return 1;
    if (L->departing && (float)(t - L->departT0) < 0.2f) return 1;
    if (L->preset != TP_NONE && !L->notrans && (float)(t - L->t0) < L->dur + 0.05f) return 1;
    return 0;
}

typedef struct { int i; int z; pn_u32 order; } LOrd;
int pn_frame_build(int vw, int vh, double t) {
    g_built = 0;
    pn_ensure_init();
    if (vw <= 0 || vh <= 0) return 0;
    lock();
    float dt = pn_s.last > 0 ? (float)(t - pn_s.last) : 0.016f; if (dt < 0 || dt > 0.1f) dt = 0.016f;
    pn_s.last = t; pn_s.now = t; pn_s.frames++;
    layers_update(t, dt);
    float gt = pn_s.show ? 1.f : 0.f;
    if (pn_s.gfade != gt) { pn_s.gfade += (gt > pn_s.gfade ? 1.f : -1.f) * dt / 0.15f; pn_s.gfade = pn_clampf(pn_s.gfade, 0, 1); }
    /* draw order: z, then age */
    LOrd ord[PN_MAX_LAYERS]; int n = 0;
    for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE && pn_s.layers[i].sc && !pn_s.layers[i].waiting) { ord[n].i = i; ord[n].z = pn_s.layers[i].sc->z; ord[n].order = pn_s.layers[i].order; n++; }
    for (int a = 1; a < n; a++) { LOrd k = ord[a]; int b = a - 1; while (b >= 0 && (ord[b].z > k.z || (ord[b].z == k.z && ord[b].order > k.order))) { ord[b + 1] = ord[b]; b--; } ord[b + 1] = k; }
    if (!n || pn_s.gfade <= 0.f) { pn_s.claimed = 0; pn_hits_reset(); g_lastTick = pn_s.tick - 1; unlock(); return 0; }
    /* idle frame: nothing changed since the last build and the renderer still holds every layer's picture ->
       reuse it (a full build every 30 frames is the safety net against anything the activity scan misses) */
    {
        int active = pn_s.tick != g_lastTick || pn_s.vw != vw || pn_s.vh != vh || pn_s.gfade != gt || ++g_sinceFull >= 30 || !pr_cache_ready();
        if (!active && pn_tex_waiting()) active = 1;   /* a head picture being made for something on screen */
        for (int k = 0; !active && k < n; k++) { PnLayer *L = &pn_s.layers[ord[k].i]; if (layer_active(L, t) || pn_scene_active(L->sc, t)) active = 1; }
        if (!active) { unlock(); g_built = 2; return 1; }
        g_sinceFull = 0; g_lastTick = pn_s.tick;
    }
    pn_s.vw = vw; pn_s.vh = vh; pn_s.unit = (float)vh / 640.f; pn_s.stageH = 640.f; pn_s.stageW = (float)vw / pn_s.unit;
    /* modal floor: the top open modal layer blocks input below it */
    pn_modal_floor = 0;
    for (int k = n - 1; k >= 0; k--) { PnLayer *L = &pn_s.layers[ord[k].i]; if (L->state == L_OPEN && L->sc->modal && L->wd > 0.5f) { pn_modal_floor = ord[k].i; break; } }
    int floorK = -1; if (pn_modal_floor) for (int k = 0; k < n; k++) if (ord[k].i == pn_modal_floor) floorK = k;
    pn_hits_reset();
    pr_begin(vw, vh);
    pn_s.dynRamp = 0;
    /* layer indices in hits are layer slots; the modal floor compares draw order, so remap: hits below floorK are ignored */
    for (int k = 0; k < n; k++) {
        PnLayer *L = &pn_s.layers[ord[k].i]; PnScene *sc = L->sc;
        layer_progress(L, t); layer_depart(L, t);
        float a = L->lalpha * L->wd * pn_s.gfade;
        pn_layout_scene(sc, pn_s.stageW, pn_s.stageH, t);
        pn_animate_scene(sc, dt, t);
        if (a <= 0.002f) continue;
        if (sc->modal && L->state != L_EXIT) {
            /* dim what is below the popup: its own entry, drawn live (one flat quad), so the popup's picture stays small */
            pr_layer_begin(ord[k].i, 1, a, 0, 1);
            PrShape sh; pn_memset(&sh, 0, sizeof(sh)); sh.shape = PS_RECT; sh.hw = (float)vw * .5f + 2; sh.hh = (float)vh * .5f + 2;
            PnFill f; pn_memset(&f, 0, sizeof(f)); f.ramp = -1; f.type = PF_SOLID; f.color = sc->dim;
            pr_fill((float)vw * .5f, (float)vh * .5f, &sh, &f, 1.f);
            pr_layer_end();
        }
        /* the layer is drawn unslid, unscaled and at full alpha: the renderer caches that picture and applies the
           transition (slide of the target subtree, scale about the centre, alpha) when it puts it on screen */
        Xf xf; xf.a = pn_s.unit; xf.bx = 0; xf.by = 0; xf.rc = 1; xf.rs = 0; xf.rx = 0; xf.ry = 0;
        int interactive = L->state == L_OPEN && !L->departing && L->wd > 0.5f && pn_s.gfade > 0.5f && (floorK < 0 || k >= floorK);
        pr_layer_begin(ord[k].i, 0, a, L->lx * pn_s.stageW * pn_s.unit, L->ls);
        pn_draw_scene(L, sc, xf, 1.f, ord[k].i, interactive);
        pr_layer_end();
    }
    /* the modal floor as a layer slot for pn_touch */
    unlock();
    g_built = 1;
    return 1;
}
static int g_gpuHeld; static pn_u32 g_idleN;
void pn_frame_submit(PnDrawSlotFn drawSlot) { if (g_built == 1) pr_end(drawSlot); else if (g_built == 2) pr_end_cached(drawSlot); if (g_built) { g_gpuHeld = 1; g_idleN = 0; } g_built = 0; }
/* GPU housekeeping for a swap in which Prism draws nothing (GL thread, the context Prism used is current): every native
   screen is gone, or all are hidden behind a stock screen (Settings). The stock screen now on top needs the memory, and
   Prism used to keep all of it: the cached pictures of screens long gone (a frame was needed to free them, and after the
   last screen there was none), the art, the fonts. The pictures of layers that are gone are freed at once; the rest goes
   2 frames into a hide, or 20 frames after the last screen (a hop between two native screens through a stock state is
   shorter, and keeps everything). The next native frame builds it all again, as after a lost context. */
int pn_gpu_held(void) { return g_gpuHeld; }
int pn_gpu_idle(void) {
    if (!g_gpuHeld) return 0;
    pr_sweep();
    int hidden = pn_active();
    if (++g_idleN < (hidden ? 2u : 20u)) return 0;
    pn_u32 pics = pr_gpu_bytes(), art = pn_assets_gpu_bytes();
    pn_assets_gl_release(); pr_release_all();
    pn_s.rampsDirty = 1; pn_s.rampLo = 0; pn_s.rampHi = PN_MAX_RAMPS - 1;
    g_gpuHeld = 0; g_idleN = 0;
    char b[200]; PnStr sb; pn_sb_init(&sb, b, sizeof b);
    pn_sb_add(&sb, "gpu: released "); pn_sb_int(&sb, (long)((pics + art) >> 10)); pn_sb_add(&sb, " KB (cached pictures ");
    pn_sb_int(&sb, (long)(pics >> 10)); pn_sb_add(&sb, " KB, art and fonts "); pn_sb_int(&sb, (long)(art >> 10));
    pn_sb_add(&sb, hidden ? " KB): the native screens are hidden behind a stock screen" : " KB): no native screen left");
    PN_LOG(b);
    return 1;
}
pn_u32 pn_gpu_bytes(void) { return pr_gpu_bytes() + pn_assets_gpu_bytes(); }

/* ---------------------------------------------------------------- commands */
static char g_reply[4200];
static void reply(const char *key, const char *val) { if (pn_host.reply) pn_host.reply(key, val); }
static void tok_of(const char *s, pn_u32 n, char *tok, pn_u32 cap) { PnStr t; pn_sb_init(&t, tok, cap); if (s) pn_sb_addn(&t, s, n < 30 ? n : 30); }
static pn_u32 field_len(const char *s, char sep) { pn_u32 n = 0; while (s[n] && s[n] != sep) n++; return n; }

static void theme_set(const char *p) {
    /* "k=#RRGGBB;k2=@other;..." */
    while (*p) {
        const char *e = p; while (*e && *e != ';') e++;
        const char *eq = p; while (eq < e && *eq != '=') eq++;
        if (eq < e && eq > p) {
            char key[24], val[40]; PnStr a, b; pn_sb_init(&a, key, sizeof(key)); pn_sb_addn(&a, p, (pn_u32)(eq - p)); pn_sb_init(&b, val, sizeof(val)); pn_sb_addn(&b, eq + 1, (pn_u32)(e - eq - 1));
            pn_s16 ti = pn_token_find(key, 1); PnColor c;
            if (ti >= 0 && pn_parse_color_str(val, &c)) { pn_s.tokens[ti].c = c; pn_s.tokens[ti].fromLua = 1; }
        }
        p = *e ? e + 1 : e;
    }
    /* re-tint every live scene; gradients get fresh ramp rows */
    { void pn_ramps_clear(void); pn_ramps_clear(); }
    for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE && pn_s.layers[i].sc) { pn_tokens_apply(pn_s.layers[i].sc); pn_ramps_reset_scene(pn_s.layers[i].sc); }
}

static int run_command(const char *cmd);
int pn_command(const char *cmd) {
    if (!cmd) return 0;
    pn_ensure_init();
    if (pn_starts(cmd, "ui:")) cmd += 3;
    /* chunked commands: "+<cid>:<part>" ... "=<cid>:<last part>" */
    if ((cmd[0] == '+' || cmd[0] == '=') && cmd[1] && cmd[2] == ':') {
        char c = cmd[1]; int ci = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'z' ? c - 'a' + 10 : -1;
        if (ci < 0) return 1;
        const char *part = cmd + 3; pn_u32 n = pn_strlen(part);
        if (pn_s.chunkLen[ci] + n + 1 > pn_s.chunkCap[ci]) {
            pn_u32 cap = (pn_s.chunkLen[ci] + n + 1) * 2; if (cap < 1024) cap = 1024;
            char *b = (char *)pn_alloc(cap); if (!b) { pn_s.chunkLen[ci] = 0; return 1; }
            if (pn_s.chunk[ci]) { pn_memcpy(b, pn_s.chunk[ci], pn_s.chunkLen[ci]); pn_free(pn_s.chunk[ci]); }
            pn_s.chunk[ci] = b; pn_s.chunkCap[ci] = cap;
        }
        pn_memcpy(pn_s.chunk[ci] + pn_s.chunkLen[ci], part, n); pn_s.chunkLen[ci] += n; pn_s.chunk[ci][pn_s.chunkLen[ci]] = 0;
        if (cmd[0] == '=') { pn_s.chunkLen[ci] = 0; const char *full = pn_s.chunk[ci]; if (pn_starts(full, "ui:")) full += 3; run_command(full); }
        return 1;
    }
    return run_command(cmd);
}

/* values for one layer from another thread (Prism Workers' animation tracks): the layer lookup, the values and the change
   tick all under the lock (pn_command's chunk buffers belong to the game's Lua thread and are not touched) */
int pn_set_values(const char *layer, const char *records) {
    if (!layer || !records) return 0;
    pn_ensure_init();
    lock(); int li = layer_find_n(layer, pn_strlen(layer)); if (li >= 0) { pn_apply_values(pn_s.layers[li].sc, records); pn_s.tick++; } unlock();
    return li >= 0;
}
static int run_command(const char *cmd) {
    if (!(pn_starts(cmd, "poll") || pn_starts(cmd, "hit:") || pn_starts(cmd, "probe:") || pn_starts(cmd, "hello") || pn_starts(cmd, "log:"))) pn_s.tick++;
    if (pn_starts(cmd, "cache:")) { pr_cache_enable(cmd[6] != '0'); return 1; }
    if (pn_starts(cmd, "log:")) { PN_LOG2("lua: ", cmd + 4); return 1; }   /* a PrismSkin.lua line into preview.log */
    if (pn_starts(cmd, "v:")) {
        /* v:<layer>|<records> */
        const char *a = cmd + 2; pn_u32 n = field_len(a, '|'); if (!a[n]) return 1;
        lock(); int li = layer_find_n(a, n); if (li >= 0) pn_apply_values(pn_s.layers[li].sc, a + n + 1); unlock();
        return 1;
    }
    if (pn_starts(cmd, "a:")) {
        /* a:<layer>|<list>|<nrows>|<rows> */
        const char *a = cmd + 2; pn_u32 n1 = field_len(a, '|'); if (!a[n1]) return 1;
        const char *b = a + n1 + 1; pn_u32 n2 = field_len(b, '|'); if (!b[n2]) return 1;
        const char *c = b + n2 + 1; pn_u32 n3 = field_len(c, '|');
        pn_u32 rows = 0; for (pn_u32 k = 0; k < n3; k++) if (c[k] >= '0' && c[k] <= '9') rows = rows * 10 + (pn_u32)(c[k] - '0');
        const char *data = c[n3] ? c + n3 + 1 : "";
        char lname[48]; PnStr sb; pn_sb_init(&sb, lname, sizeof(lname)); pn_sb_addn(&sb, b, n2);
        lock(); int li = layer_find_n(a, n1);
        if (li >= 0) { PnList *L = pn_list_find(pn_s.layers[li].sc, lname); if (L) pn_list_set_rows(pn_s.layers[li].sc, L, rows, data); }
        unlock();
        return 1;
    }
    if (pn_starts(cmd, "sel:")) {
        const char *a = cmd + 4; pn_u32 n1 = field_len(a, '|'); if (!a[n1]) return 1;
        const char *b = a + n1 + 1; pn_u32 n2 = field_len(b, '|'); if (!b[n2]) return 1;
        char lname[48]; PnStr sb; pn_sb_init(&sb, lname, sizeof(lname)); pn_sb_addn(&sb, b, n2);
        int idx = 0, neg = 0; const char *q = b + n2 + 1; if (*q == '-') { neg = 1; q++; } while (*q >= '0' && *q <= '9') idx = idx * 10 + (*q++ - '0');
        lock(); int li = layer_find_n(a, n1);
        if (li >= 0) { PnList *L = pn_list_find(pn_s.layers[li].sc, lname); if (L) { L->sel = neg ? -1 : idx; L->toTarget = 2; } }
        unlock();
        return 1;
    }
    if (pn_starts(cmd, "poll")) {
        /* poll:<tok>|<alive ids> */
        const char *a = cmd[4] == ':' ? cmd + 5 : ""; pn_u32 n = field_len(a, '|');
        char tok[32]; tok_of(a, n, tok, sizeof(tok));
        double tn = now();
        lock();
        if (a[n] == '|') {
            const char *p = a + n + 1;
            if (p[0] == '*' && !p[1]) { for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE) layer_polled(&pn_s.layers[i], tn); }
            else while (*p) { pn_u32 m = field_len(p, ','); int li = layer_find_n(p, m); if (li >= 0) layer_polled(&pn_s.layers[li], tn); p += m; if (*p == ',') p++; }
        }
        int any = 0; for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state == L_OPEN) any = 1;
        int gl = pr_gl_state();
        PnStr sb; pn_sb_init(&sb, g_reply, sizeof(g_reply));
        pn_sb_add(&sb, "s"); pn_sb_ch(&sb, any ? '1' : '0');
        pn_sb_ch(&sb, pn_s.touchOk > 0 ? '1' : pn_s.touchOk < 0 ? 'x' : '0'); pn_sb_ch(&sb, gl > 0 ? '1' : gl < 0 ? 'x' : '0');
        pn_sb_ch(&sb, ':'); pn_sb_add(&sb, tok);
        if (pn_s.evlen) { pn_sb_ch(&sb, '\x1e'); pn_sb_add(&sb, pn_s.events); }
        pn_s.evlen = 0; pn_s.events[0] = 0;
        unlock();
        reply("PRISM_UI_EV", g_reply);
        return 1;
    }
    if (pn_starts(cmd, "hello")) {
        char tok[32]; const char *a = cmd[5] == ':' ? cmd + 6 : ""; tok_of(a, pn_strlen(a), tok, sizeof(tok));
        PnStr sb; pn_sb_init(&sb, g_reply, 300);
        pn_sb_add(&sb, "ok;v="); pn_sb_add(&sb, PN_VERSION_STR); pn_sb_add(&sb, ";tok="); pn_sb_add(&sb, tok);
        pn_sb_add(&sb, ";touch="); pn_sb_int(&sb, pn_s.touchOk); pn_sb_add(&sb, ";gl="); pn_sb_int(&sb, pr_gl_state());
        /* waitpolls (R98e): a waiting layer is dropped only once Lua had its polls, or after 30 s (layers_update) */
        pn_sb_add(&sb, ";caps=layers,lists,motion,theme,chunk,waitpolls;vw="); pn_sb_int(&sb, pn_s.vw); pn_sb_add(&sb, ";vh="); pn_sb_int(&sb, pn_s.vh);
        PN_LOG2("hello: ", g_reply);
        /* a new PrismSkin (the game reloaded its Lua) knows of no hidden state: start shown */
        lock(); if (!pn_s.show) { pn_s.show = 1; PN_LOG("ui: shown (a new PrismSkin said hello)"); } unlock();
        reply("PRISM_UI", g_reply);
        return 1;
    }
    if (pn_starts(cmd, "probe:")) {
        /* probe:<tok>:<n>:<payload> -> "<tok>:<received payload length>" */
        const char *a = cmd + 6; pn_u32 n1 = field_len(a, ':'); if (!a[n1]) return 1;
        char tok[32]; tok_of(a, n1, tok, sizeof(tok));
        const char *b = a + n1 + 1; pn_u32 n2 = field_len(b, ':');
        pn_u32 got = b[n2] ? pn_strlen(b + n2 + 1) : 0;
        PnStr sb; pn_sb_init(&sb, g_reply, 100); pn_sb_add(&sb, tok); pn_sb_ch(&sb, ':'); pn_sb_int(&sb, (long)got);
        reply("PRISM_UI_PROBE", g_reply);
        return 1;
    }
    if (pn_starts(cmd, "open:")) {
        /* open:<layer>|<path>|<tok>[|flags] */
        const char *a = cmd + 5; pn_u32 n1 = field_len(a, '|'); if (!a[n1]) return 1;
        const char *b = a + n1 + 1; pn_u32 n2 = field_len(b, '|');
        const char *c = b[n2] ? b + n2 + 1 : ""; pn_u32 n3 = field_len(c, '|');
        const char *fl = c[n3] ? c + n3 + 1 : "";
        char id[48], path[200], tok[32]; PnStr s1, s2; pn_sb_init(&s1, id, sizeof(id)); pn_sb_addn(&s1, a, n1); pn_sb_init(&s2, path, sizeof(path)); pn_sb_addn(&s2, b, n2);
        tok_of(c, n3, tok, sizeof(tok));
        int back = 0, notrans = 0, keep = 0, wait = 0;
        for (const char *q = fl; *q; ) { pn_u32 m = field_len(q, ','); if (m == 4 && pn_strneq(q, "back", 4)) back = 1; else if (m == 7 && pn_strneq(q, "notrans", 7)) notrans = 1; else if (m == 4 && pn_strneq(q, "keep", 4)) keep = 1; else if (m == 4 && pn_strneq(q, "wait", 4)) wait = 1; q += m; if (*q == ',') q++; }
        PnStr sb; pn_sb_init(&sb, g_reply, 400);
        double tn = now();
        lock();
        int li = layer_find(id);
        if (li >= 0 && keep && pn_s.layers[li].sc && pn_streq(pn_s.layers[li].sc->path, path)) {
            /* already there (shell): just keep it alive */
            PnLayer *L = &pn_s.layers[li]; if (L->state != L_OPEN) { L->state = L_OPEN; L->t0 = tn; } L->lastPoll = tn;
            unlock();
            pn_sb_add(&sb, "ok:"); pn_sb_add(&sb, id); pn_sb_ch(&sb, ':'); pn_sb_add(&sb, tok); reply("PRISM_UI_LOAD", g_reply);
            return 1;
        }
        unlock();
        const char *err = NULL;
        PnScene *sc = pn_scene_build(path, &err);
        if (!sc) { PN_ERR("open: ", err); pn_sb_add(&sb, "err:"); pn_sb_add(&sb, err); pn_sb_ch(&sb, ':'); pn_sb_add(&sb, tok); reply("PRISM_UI_LOAD", g_reply); return 1; }
        lock();
        li = layer_find(id); if (li >= 0) layer_free(li);
        li = layer_alloc();
        if (li < 0) { unlock(); pn_scene_free(sc); pn_sb_add(&sb, "err:too many layers:"); pn_sb_add(&sb, tok); reply("PRISM_UI_LOAD", g_reply); return 1; }
        PnLayer *L = &pn_s.layers[li]; pn_memset(L, 0, sizeof(*L));
        pn_sb_init(&s1, L->id, sizeof(L->id)); pn_sb_add(&s1, id);
        L->sc = sc; L->state = L_OPEN; L->order = ++pn_s.layerOrder; L->openedAt = L->lastPoll = tn; L->t0 = tn; L->wd = 1.f;
        L->notrans = (pn_u8)notrans;
        pn_tokens_apply(sc);
        /* a successor exists: screens held after a leave wait for it (re-armed hold; they also wait while it is not ready) */
        if (!sc->shell) for (int k = 0; k < PN_MAX_LAYERS; k++) { PnLayer *H = &pn_s.layers[k]; if (H != L && H->state == L_HELD) { H->heldAt = tn; if (H->holdFor < 0.6f) H->holdFor = 0.6f; } }
        if (wait) { L->waiting = 1; L->dir = (pn_s8)(back ? -1 : 0); }
        else layer_activate(L, back, tn);
        unlock();
        PN_LOG2("open: ", sc->id);
        pn_sb_add(&sb, "ok:"); pn_sb_add(&sb, id); pn_sb_ch(&sb, ':'); pn_sb_add(&sb, tok);
        reply("PRISM_UI_LOAD", g_reply);
        return 1;
    }
    if (pn_starts(cmd, "ready:")) {
        lock(); int li = layer_find(cmd + 6);
        if (li >= 0 && pn_s.layers[li].waiting) { PnLayer *L = &pn_s.layers[li]; L->waiting = 0; layer_activate(L, L->dir < 0, now()); }
        unlock(); return 1;
    }
    if (pn_starts(cmd, "leave:")) {
        /* leave:<layer>[|solo] - solo: no other native screen exists to take over, so the left screen is not kept long */
        const char *lid = cmd + 6; pn_u32 ln = field_len(lid, '|'); int solo = lid[ln] == '|' && pn_starts(lid + ln + 1, "solo");
        lock(); int li = layer_find_n(lid, ln);
        /* Lua's 'solo' is a guess (the next screen's VM is created after this one is finalized), so even a solo leave
           holds long enough for a native successor's open to arrive and take over without a gap */
        if (li >= 0 && pn_s.layers[li].state == L_OPEN) pn_s.layers[li].holdFor = solo ? 0.35f : 0.6f;
        if (li >= 0 && pn_s.layers[li].waiting) layer_free(li);
        else if (li >= 0 && pn_s.layers[li].state == L_OPEN) {
            PnLayer *L = &pn_s.layers[li];
            if (L->sc->modal || L->sc->z >= 20) start_exit(L, L->sc->preset == TP_RISE ? TP_RISE : TP_FADE, 1, now());
            else { L->state = L_HELD; L->heldAt = now(); }
        }
        unlock(); return 1;
    }
    if (pn_starts(cmd, "close:")) { lock(); int li = layer_find(cmd + 6); if (li >= 0) layer_free(li); unlock(); return 1; }
    if (pn_starts(cmd, "depart:")) {
        /* depart:<layer>|<dir> - a tap on it navigated away (Lua sends this from the stock nav call): its content slides
           out now. Only a full screen over the shell (the room stays, so nothing black shows while the next one builds) */
        const char *lid = cmd + 7; pn_u32 ln = field_len(lid, '|'); int dir = lid[ln] == '|' && lid[ln + 1] == '-' ? -1 : 1;
        lock(); int li = layer_find_n(lid, ln);
        int shell = 0; for (int k = 0; k < PN_MAX_LAYERS; k++) { PnLayer *H = &pn_s.layers[k]; if (H->state != L_FREE && H->sc && H->sc->shell && !H->waiting) shell = 1; }
        if (li >= 0 && shell) {
            PnLayer *L = &pn_s.layers[li];
            if (L->state == L_OPEN && !L->waiting && !L->departing && L->sc && !L->sc->shell && !L->sc->modal && L->sc->z < 20) {
                L->departing = 1; L->departDir = (pn_s8)dir; L->departT0 = now(); pn_s.tick++;
            }
        }
        unlock(); return 1;
    }
    if (pn_starts(cmd, "undepart:")) {
        /* the screen is still there (the nav did not change screens): it comes back */
        lock(); int li = layer_find(cmd + 9);
        if (li >= 0 && pn_s.layers[li].departing == 1 && pn_s.layers[li].state == L_OPEN) { pn_s.layers[li].departing = 2; pn_s.layers[li].departT0 = now(); pn_s.tick++; }
        unlock(); return 1;
    }
    if (pn_starts(cmd, "dir:")) { pn_s.dirNext = pn_starts(cmd + 4, "back") ? -1 : 1; return 1; }
    if (pn_starts(cmd, "play:")) {
        /* play:<layer>|<node name or *>|<timeline> */
        const char *a = cmd + 5; pn_u32 n1 = field_len(a, '|'); if (!a[n1]) return 1;
        const char *b = a + n1 + 1; pn_u32 n2 = field_len(b, '|'); if (!b[n2]) return 1;
        const char *c = b + n2 + 1;
        lock(); int li = layer_find_n(a, n1);
        if (li >= 0) {
            PnScene *sc = pn_s.layers[li].sc; PnTL *tl = pn_tl_find(sc, c);
            if (tl) {
                /* "*" = the root; a node name plays on every node with that name (row templates included); a number = node index */
                if (n2 == 1 && b[0] == '*') pn_play(&sc->nodes[0], tl, now(), 0);
                else {
                    int idx = 0; int isNum = n2 > 0; for (pn_u32 k = 0; k < n2; k++) { if (b[k] < '0' || b[k] > '9') isNum = 0; else idx = idx * 10 + (b[k] - '0'); }
                    if (isNum) { if ((pn_u32)idx < sc->nnodes) pn_play(&sc->nodes[idx], tl, now(), 0); }
                    else { pn_u32 h = pn_hashn(b, n2); for (pn_u32 k = 0; k < sc->nnodes; k++) if (sc->nodes[k].nameHash == h) pn_play(&sc->nodes[k], tl, now(), 0); }
                }
            }
        }
        unlock(); return 1;
    }
    if (pn_starts(cmd, "theme:")) { lock(); theme_set(cmd + 6); unlock(); return 1; }
    if (pn_starts(cmd, "preload:")) { pn_scene_preload(cmd + 8); return 1; }
    if (pn_streq(cmd, "show")) { lock(); int was = pn_s.show; pn_s.show = 1; unlock(); if (!was) PN_LOG("ui: shown again (the stock screen over the native ones closed)"); return 1; }
    if (pn_streq(cmd, "hide")) { lock(); int was = pn_s.show; pn_s.show = 0; unlock(); if (was) PN_LOG("ui: hidden (a stock screen opens over the native ones; touches go to the game)"); return 1; }
    if (pn_streq(cmd, "reset")) { lock(); for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE) layer_free(i); unlock(); return 1; }
    if (pn_starts(cmd, "roots:")) { pn_set_roots(cmd + 6); pn_s.lastRoot[0] = 0; pn_scene_cache_drop(); return 1; }
    if (pn_starts(cmd, "debug:")) { pn_s.debug = cmd[6] == '1'; return 1; }
    if (pn_streq(cmd, "dump")) { pn_debug_dump(); return 1; }
    if (pn_starts(cmd, "hit:")) {
        /* hit:<layer>|<action>[|row] -> "x0,y0,x1,y1" (px) or "none" */
        const char *a = cmd + 4; pn_u32 n1 = field_len(a, '|'); if (!a[n1]) return 1;
        const char *b = a + n1 + 1; pn_u32 n2 = field_len(b, '|');
        char id[48], act[64]; PnStr s1, s2; pn_sb_init(&s1, id, sizeof(id)); pn_sb_addn(&s1, a, n1); pn_sb_init(&s2, act, sizeof(act)); pn_sb_addn(&s2, b, n2);
        int row = -1; if (b[n2] == '|') { row = 0; for (const char *q = b + n2 + 1; *q >= '0' && *q <= '9'; q++) row = row * 10 + (*q - '0'); }
        float box[4]; int pn_hit_box(const char *layer, const char *action, int row, float *box);
        lock(); int found = pn_hit_box(id, act, row, box); unlock();
        PnStr sb; pn_sb_init(&sb, g_reply, 200);
        if (found) { pn_sb_float(&sb, box[0], 1); pn_sb_ch(&sb, ','); pn_sb_float(&sb, box[1], 1); pn_sb_ch(&sb, ','); pn_sb_float(&sb, box[2], 1); pn_sb_ch(&sb, ','); pn_sb_float(&sb, box[3], 1); }
        reply("PRISM_UI_HIT", found ? g_reply : "none");
        return 1;
    }
    return 0;
}

const char *pn_last_reply(const char *key) { (void)key; return g_reply; }

void pn_debug_dump(void) {
    char buf[600]; PnStr sb; pn_sb_init(&sb, buf, sizeof(buf));
    pn_sb_add(&sb, "dump: layers=");
    for (int i = 0; i < PN_MAX_LAYERS; i++) {
        PnLayer *L = &pn_s.layers[i]; if (L->state == L_FREE) continue;
        pn_sb_add(&sb, L->id); pn_sb_ch(&sb, '('); pn_sb_add(&sb, L->sc ? L->sc->id : "?"); pn_sb_ch(&sb, ' '); pn_sb_ch(&sb, "-OHE"[L->state]);
        if (L->sc) { pn_sb_add(&sb, " n="); pn_sb_int(&sb, (long)L->sc->nnodes); }
        pn_sb_add(&sb, ") ");
    }
    pn_sb_add(&sb, " quads="); pn_sb_int(&sb, (long)pn_s.quads); pn_sb_add(&sb, " draws="); pn_sb_int(&sb, (long)pn_s.drawCalls);
    pn_sb_add(&sb, " fonts="); pn_sb_int(&sb, (long)pn_s.nfonts); pn_sb_add(&sb, " textures="); pn_sb_int(&sb, (long)pn_s.ntex);
    pn_sb_add(&sb, " stage="); pn_sb_int(&sb, (long)pn_s.stageW); pn_sb_ch(&sb, 'x'); pn_sb_int(&sb, (long)pn_s.stageH);
    pn_sb_add(&sb, " px="); pn_sb_int(&sb, pn_s.vw); pn_sb_ch(&sb, 'x'); pn_sb_int(&sb, pn_s.vh);
    PN_LOG(buf);
}

void pn_gl_lost(void) { g_gpuHeld = 0; g_idleN = 0; pr_lost(); pn_assets_gl_lost(); pn_s.rampsDirty = 1; pn_s.rampLo = 0; pn_s.rampHi = PN_MAX_RAMPS - 1; for (pn_u32 i = 0; i < pn_s.nfonts; i++) pn_s.fonts[i].tex = 0; }
