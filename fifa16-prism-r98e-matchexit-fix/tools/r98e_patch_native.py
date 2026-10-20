"""Applies the R98e Prism Native changes (the waiting deadline counts the Lua thread's polls) to <dir>/pn_int.h and
<dir>/pn_core.c for every <dir> given; each anchor must occur once."""
import os, sys

INT_H = [
("""    pn_u8 state, preset, notrans, waiting;
""",
"""    pn_u8 state, preset, notrans, waiting;
    pn_u32 waitPolls;              /* Lua polls since the open while it waits for its ready (the deadline counts them) */
"""),
]
CORE_C = [
("""static void layers_update(double t, float dt) {
""",
"""/* A layer opened with "wait" that never became ready is dropped: a screen whose open was abandoned must not keep the
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
"""),
("""        if (L->waiting) { if (t - L->openedAt > 3.0) { PN_WARN("open: layer never became ready, dropped: ", L->id); layer_free(i); } continue; }
""",
"""        if (L->waiting) { if ((t - L->openedAt > 3.0 && L->waitPolls >= PN_WAIT_POLLS) || t - L->openedAt > 30.0) { PN_WARN("open: layer never became ready, dropped: ", L->id); layer_free(i); } continue; }
"""),
("""    for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE) pn_s.layers[i].lastPoll = tn;
    int any = 0; for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state == L_OPEN) any = 1;
    int gl = pr_gl_state();
    PnStr sb; pn_sb_init(&sb, out, cap);
""",
"""    for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE) layer_polled(&pn_s.layers[i], tn);
    int any = 0; for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state == L_OPEN) any = 1;
    int gl = pr_gl_state();
    PnStr sb; pn_sb_init(&sb, out, cap);
"""),
("""            if (p[0] == '*' && !p[1]) { for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE) pn_s.layers[i].lastPoll = tn; }
            else while (*p) { pn_u32 m = field_len(p, ','); int li = layer_find_n(p, m); if (li >= 0) pn_s.layers[li].lastPoll = tn; p += m; if (*p == ',') p++; }
""",
"""            if (p[0] == '*' && !p[1]) { for (int i = 0; i < PN_MAX_LAYERS; i++) if (pn_s.layers[i].state != L_FREE) layer_polled(&pn_s.layers[i], tn); }
            else while (*p) { pn_u32 m = field_len(p, ','); int li = layer_find_n(p, m); if (li >= 0) layer_polled(&pn_s.layers[li], tn); p += m; if (*p == ',') p++; }
"""),
("""        pn_sb_add(&sb, ";caps=layers,lists,motion,theme,chunk;vw="); pn_sb_int(&sb, pn_s.vw); pn_sb_add(&sb, ";vh="); pn_sb_int(&sb, pn_s.vh);
""",
"""        /* waitpolls (R98e): a waiting layer is dropped only once Lua had its polls, or after 30 s (layers_update) */
        pn_sb_add(&sb, ";caps=layers,lists,motion,theme,chunk,waitpolls;vw="); pn_sb_int(&sb, pn_s.vw); pn_sb_add(&sb, ";vh="); pn_sb_int(&sb, pn_s.vh);
"""),
]

def apply(path, edits):
    s = open(path, encoding='utf-8').read()
    for old, new in edits:
        n = s.count(old)
        assert n == 1, '%s: anchor found %d times: %r' % (path, n, old[:80])
        s = s.replace(old, new)
    open(path, 'w', encoding='utf-8').write(s)
    print('patched', path)

for d in sys.argv[1:]:
    apply(os.path.join(d, 'pn_int.h'), INT_H)
    apply(os.path.join(d, 'pn_core.c'), CORE_C)
