/* pn_int.h - Prism Native 4 internals shared by every file.
 *
 * Prism Native draws "layers": each layer is one scene (a Zinc-style widget tree with a "pn" object of native
 * styling, lists, motion and states on its nodes) owned by one Lua screen. Layers stack by z, transition in pairs
 * (the old screen stays drawn until the new one is ready, then both animate) and are composited every frame from
 * the eglSwapBuffers hook. */
#ifndef PN_INT_H
#define PN_INT_H
#include "pn.h"
#include "pn_json.h"
#include "pn_image.h"

typedef struct { float r, g, b, a; } PnColor; /* straight alpha, 0..1 */

/* ---------------------------------------------------------------- vector paint (mirrors tools/paint.js) */
enum { PF_NONE = 0, PF_SOLID, PF_LINEAR, PF_RADIAL };
#define PN_MAX_STOPS 8
typedef struct {
    pn_u8 type, nstops; pn_s16 ramp;  /* ramp: row in the gradient texture, -1 until allocated */
    PnColor color;                     /* solid colour */
    float angle, cx, cy, r;            /* linear angle (deg, CSS) / radial centre + radius (fractions of the box) */
    float stopT[PN_MAX_STOPS]; PnColor stopC[PN_MAX_STOPS];
} PnFill;
typedef struct { pn_u8 on, inside; float x, y, blur, spread; PnColor color; } PnFx;

enum { PS_RECT = 0, PS_PILL, PS_CIRCLE, PS_DIAMOND, PS_POLY };
enum { PO_BAND = 0, PO_CIRCLE, PO_RECT, PO_ICON };
enum { PB_NORMAL = 0, PB_ADD };
typedef struct {
    pn_u8 kind, blend; pn_s16 tex;
    float a, b, c, d;     /* band: angle offset width - | circle: x y r - | rect: x y w h | icon: x y size - */
    float radius;
    PnFill fill; float opacity; PnFx glow;
} PnOverlay;
typedef struct PnPaint {
    pn_u8 shape, npts, border, borderAlign, vignette, nov;
    float radius[4];               /* tl tr br bl, engine units */
    float pts[24];                 /* poly points (engine units, relative to the box at design size) */
    float designW, designH;
    PnFill fill, borderFill; float borderW;
    PnFx shadow, glow, inner;
    float opacity, blur;           /* blur > 0: frosted glass */
    PnColor vig;
    float pad;
    PnOverlay *ov;
    pn_s16 tex;                    /* -2: the node carries a rasterised fallback ("img/x.png") */
    pn_u8 needTex;
} PnPaint;

enum { FR_RING = 0, FR_BAR, FR_STAR };
typedef struct {
    pn_u8 kind, cap, hasTrack, glowOn; pn_u16 count, segments;
    float tw;
    float r, t, start, sweep, pad;
    float bw, bh, br, gap;
    float size;
    PnFill fill; PnColor track, empty; PnFx glow;
} PnFrames;

/* ---------------------------------------------------------------- fonts / textures */
typedef struct { pn_u32 cp; pn_s16 x, y, w, h; float bx, by, adv; } PnGlyph;
typedef struct {
    char name[64], file[96];
    pn_u8 state;                   /* 0 new, 2 ready, 3 failed */
    pn_u16 aw, ah;
    float em, spread, ascent, descent, lineGap;
    PnGlyph *glyphs; pn_u32 nglyphs;
    pn_u32 *kernKeys; float *kernVals; pn_u32 nkern;
    pn_u8 *pixels;
    PnGLuint tex;
    pn_s32 ascii[128];
} PnFont;
typedef struct {
    char path[160]; pn_u32 hash;
    pn_u8 state;                   /* 0 new, 1 decoded (pending upload), 2 ready, 3 failed, 4 free slot */
    pn_u16 w, h;
    PnGLuint tex;
    PnImage img;
    pn_u8 glyph;                   /* has real transparency (an icon, not a picture): "mono" may recolour it */
    pn_u32 lastUse;                /* frame number, for eviction */
    pn_u32 gen;                    /* bumped whenever the slot is given to another path: nodes holding the slot check it */
    pn_u32 bytes;                  /* RGBA bytes on the GPU while state 2 */
    pn_u32 retryAt;                /* a picture being made elsewhere (a 3D head): ask again at this frame */
} PnTex;

/* ---------------------------------------------------------------- motion */
enum { CH_X = 0, CH_Y, CH_S, CH_SX, CH_SY, CH_ROT, CH_ALPHA, CH_PROG, CH_N };
enum { EZ_LINEAR = 0, EZ_INQUAD, EZ_OUTQUAD, EZ_INOUTQUAD, EZ_INCUBIC, EZ_OUTCUBIC, EZ_INOUTCUBIC, EZ_OUTQUART, EZ_OUTEXPO, EZ_OUTBACK, EZ_INBACK, EZ_SPRING };
#define PN_MAX_KEYS 8
typedef struct { float t; pn_u8 ease; pn_u16 mask; float v[CH_N]; } PnKey;
typedef struct PnTL {
    float dur, delay, stagger;
    pn_s16 repeat;                 /* 0 once, n extra times, -1 forever */
    pn_u8 yoyo, nkeys, ease;
    pn_u16 mask;                   /* channels this timeline drives */
    PnKey key[PN_MAX_KEYS];
} PnTL;
enum { TR_ENTER = 0, TR_EXIT, TR_SHOW, TR_HIDE, TR_LOOP, TR_TAP, TR_CHANGE, TR_N };
typedef struct { PnTL *tl[TR_N]; } PnMotion;
typedef struct { PnTL *tl; double t0; float delay; pn_u8 on; } PnPlay;
typedef struct { float v[CH_N]; } PnChans;   /* composed channel values (identity: 0 x/y/rot, 1 scales/alpha, -1 prog = none) */

/* ---------------------------------------------------------------- styles (state blend) */
typedef struct PnStyle {
    PnPaint *paint;                /* full paint for the "on" state (base merged with the override) */
    pn_u8 hasFont, hasColor, hasAlpha, hasTint;
    PnColor fontColor, color, tint;
    float alpha, tx, ty, s, rot, dur;
    pn_s32 bind;                   /* scene binding index driving it, or -1 */
    pn_s16 field;                  /* list field index driving it (row templates), or -1 */
    pn_u8 rowSel;                  /* "@sel": row is the list's selected row */
} PnStyle;

/* ---------------------------------------------------------------- scene graph */
enum { NK_PANEL = 1, NK_RECT, NK_LABEL, NK_IMAGE, NK_BUTTON, NK_GESTURE };
enum { AL_START = 0, AL_CENTER, AL_END, AL_FILL };
enum { FIT_CONTAIN = 0, FIT_COVER, FIT_FILL };
enum { P_VISIBLE = 1, P_ALPHA, P_TEXT, P_FONTCOLOR, P_COLOR, P_IMAGE, P_ML, P_MR, P_MT, P_MB, P_W, P_H, P_X, P_Y,
       P_PROGRESS, P_FILL, P_BORDER, P_GLOW, P_SHADOW, P_TINT, P_RADIUS, P_OPACITY, P_STATE, P_S, P_ROT, P_FONTSIZE };

struct PnList;
typedef struct PnNode {
    pn_u8 kind, alignH, alignV, hasW, hasH, visible, skipKids, multiline, caps, textShadow, drawFill, drawOutline;
    pn_u8 align, valign, maxLines, pressed, clip, live, fit, stOn, hiding, isTmpl, ownText, mask;
    pn_s8 slot;                    /* 3D player slot for "<ns>_player3d_N" panels, else -1 */
    pn_s32 parent, first, next, sib; /* sib: index among siblings */
    float mL, mR, mT, mB, w, h, x, y, alpha;
    /* Label */
    char *text; pn_u32 textCap; const char *rtext; pn_s16 font; float fontSize, leading, tracking; PnColor fontColor; char *face;
    float count; double countT0; float countFrom, countTo; /* count-up */
    /* Rectangle */
    PnColor color, fillC, outlineC; float corner, outlineT;
    /* Image / painted */
    PnPaint *paint, *paintOwn;     /* paintOwn: per-node copy once a runtime binding touched it */
    PnFrames *frames; pn_s16 tex, texSrc; pn_u32 texGen; char *imgName; pn_s32 imgId; PnColor tint; float imgRadius; /* tex: -1 none, -2/-3 unresolved (texSrc remembers which), >= 0 slot (valid while texGen == the slot's gen) */
    pn_u32 nameHash;               /* hash of the node's name (0 = unnamed): play:<layer>|<name>|<timeline> */
    float prog, progCur, progFrom; double progT0; /* frames value: target / shown / transition start */
    /* GenericButton, GestureArea, press flash */
    pn_s16 action, pan, pressFor; float pressAlpha, pressScale;
    struct PnList *list;
    PnStyle *st; float smix;
    PnMotion *mo; PnPlay play, loop;
    float trLayout, trAlpha, trProg; pn_u8 trEase;
    float pivX, pivY; float tfX, tfY, tfS, tfSX, tfSY, tfRot, tfA; /* static transform */
    float bS, bRot;                /* bound scale / rotation */
    pn_u8 flow, flowAlign; float flowGap; /* flow container: children placed left to right by their measured width (row aligned 0 left, 1 centre, 2 right) */
    /* runtime */
    float ax, ay, aw, ah;          /* layout box, engine units */
    float flx, fly, flw, flh; double flT0; pn_u8 flOn, laidOut; /* FLIP: box the change started from */
    float alphaCur, alphaFrom; double alphaT0;
    float vis, flash, pscale;
} PnNode;

typedef struct { pn_s32 node; pn_u8 prop; pn_s32 next; } PnRef;          /* binding -> node property */
typedef struct { pn_s32 node; pn_u8 prop; pn_s16 field; } PnFRef;        /* list field -> template node property */
typedef struct { char *name; pn_u32 hash; pn_s32 head; } PnBind;
typedef struct { PnColor *dst; PnFill *fill; pn_s16 token; float amul; } PnTokRef;

typedef struct PnList {
    pn_s32 node, tmpl;
    char name[48];                 /* the "items" binding name (a: command key) */
    pn_u8 dir, cols, snap, center, sbOn;
    float item, gap, pad0, pad1, stagger;
    pn_s16 tapAct;
    pn_s32 selBind;                /* scene binding that sets the selected index (0-based), or -1 */
    pn_u32 nfields; char **fields;
    PnFRef *frefs; pn_u32 nfrefs, frefCap;
    /* rows */
    pn_u32 nrows; char *buf; pn_u32 bufCap; char **cells; pn_u32 cellCap;
    int sel; float *selMix; pn_u32 selCap;
    /* scrolling (engine units along the list axis) */
    float scroll, vel, maxScroll, target; pn_u8 drag, toTarget;
    float dragFrom, dragScroll; double lastMoveT; float lastMovePos;
    double shownAt; int pressedRow; float pressV;
    PnColor sbTrack, sbThumb; float sbW;
    float viewLen, cross;          /* visible extent along / across the axis (units) */
} PnList;

typedef struct PnScene {
    PnArena arena;
    char id[48], path[200];
    PnNode *nodes; pn_u32 nnodes, nodeCap;
    PnBind *binds; pn_u32 nbinds, bindCap; pn_s32 *bhash; pn_u32 bmask;
    PnRef *refs; pn_u32 nrefs, refCap;
    char **actions; pn_u32 nactions, actionCap;
    PnList **lists; pn_u32 nlists, listCap;
    PnTokRef *trefs; pn_u32 ntrefs, trefCap;
    PnFill **fills; pn_u32 nfills, fillCap; /* every gradient fill, for ramp rebuilds */
    char **tlNames; PnTL **tls; pn_u32 ntl;  /* named timelines */
    char **anames, **apaths; pn_u32 nassets;
    float pressScale;
    /* layer behaviour */
    int z, depth; pn_u8 shell, modal, keep, preset;   /* keep: never faded by the watchdog (the loading screen) */ float dur, exitDur; PnColor dim; char target[48]; pn_s32 targetNode;
    int layoutDirty, hasFlow;
    float lastW, lastH;
} PnScene;

/* ---------------------------------------------------------------- layers */
enum { L_FREE = 0, L_OPEN, L_HELD, L_EXIT };
enum { TP_NONE = 0, TP_PUSH, TP_BACK, TP_FADE, TP_RISE };
#define PN_MAX_LAYERS 12
typedef struct PnLayer {
    char id[48];
    PnScene *sc;
    pn_u8 state, preset, notrans, waiting;
    pn_u32 waitPolls;              /* Lua polls since the open while it waits for its ready (the deadline counts them) */
    pn_s8 dir;                     /* +1 push, -1 back */
    pn_u32 order;
    double t0;                     /* transition start (enter or exit) */
    float dur;
    double heldAt, lastPoll, openedAt, noContentAt;
    float holdFor;                 /* how long a held (left) screen stays up waiting for its successor */
    pn_u8 departing;               /* 1: a tap navigated away, the content is sliding out to the shell; 2: coming back */
    pn_s8 departDir; double departT0;
    float wd, wdT;                 /* watchdog visibility 0..1, and its target */
    /* this frame */
    float lx, lalpha, ls;          /* layer slide (fraction of stage width), alpha, scale */
    float ox, oalpha;              /* fade-only part (non-target nodes) */
} PnLayer;

/* ---------------------------------------------------------------- global state */
#define PN_MAX_FONTS 16
#define PN_MAX_TEX 384
#define PN_MAX_RAMPS 128
#define PN_DYN_RAMPS 16            /* the last rows: per-frame rows for animated gradients */
#define PN_MAX_TOKENS 96
typedef struct { char name[24]; PnColor c; pn_u8 fromLua; } PnToken;
typedef struct {
    PnLayer layers[PN_MAX_LAYERS]; pn_u32 layerOrder;
    int show;                      /* global hide/show (game popups) */
    float gfade;
    double now, last;
    int dirNext;                   /* direction for the next transition pair */
    float stageW, stageH, unit;
    int vw, vh;
    char events[6144]; pn_u32 evlen; pn_u32 evDropped;
    char roots[512];
    char lastRoot[200];
    PnFont fonts[PN_MAX_FONTS]; pn_u32 nfonts;
    PnTex texs[PN_MAX_TEX]; pn_u32 ntex; pn_u32 texBytes; pn_u32 imgPending; /* textures waiting for a picture made elsewhere */
    PnFill *ramps[PN_MAX_RAMPS]; pn_u32 nramps; int rampsDirty; int rampLo, rampHi;
    pn_u32 dynRamp;                /* per-frame dynamic ramp rows used */
    PnToken tokens[PN_MAX_TOKENS]; pn_u32 ntokens;
    /* touch */
    volatile pn_u32 tqHead, tqTail;
    int tLayer; pn_s32 tDown, tPan, tList; int tRow; float tx0, ty0, tx, ty; int tMoved; double tDownAt;
    pn_u32 claimed;
    int debug, touchOk;
    pn_u32 frames, drawCalls, quads;
    pn_u32 tick;                   /* bumped by anything that can change the picture (commands, touches, loads) */
    /* chunked commands */
    char *chunk[36]; pn_u32 chunkLen[36], chunkCap[36];
} PnState;

extern PnState pn_s;

/* core */
void pn_queue_event(const char *a, const char *b, const char *c);
PnNode *pn_node(PnScene *sc, pn_s32 i);
int pn_parse_color_str(const char *s, PnColor *out);
pn_s16 pn_token_find(const char *name, int create);

/* draw / animation activity (pn_draw.c): 1 while any node or list of the scene is still moving */
int pn_scene_active(PnScene *sc, double now);
void pn_mark_change(void);

/* renderer frame cache (pn_render.c): each layer's quads are recorded between these; cached per layer slot */
void pr_layer_begin(int slot, int dim, float alpha, float dx, float ls);
void pr_layer_end(void);
void pr_set_group(int g);          /* 1 while drawing the subtree the layer slide applies to */
void pr_layer_free(int slot);
void pr_cache_enable(int on);       /* ui:cache:0|1 (tests, diagnostics) */
int pr_cache_ready(void);          /* every layer of the last frame is in the cache (an idle frame can skip the build) */
void pr_end_cached(PnDrawSlotFn drawSlot);

/* scene (pn_scene.c) */
PnScene *pn_scene_build(const char *rel, const char **err);
void pn_scene_free(PnScene *sc);
void pn_scene_cache_drop(void);
int pn_scene_preload(const char *rel);
pn_s32 pn_bind_find(PnScene *sc, const char *name, pn_u32 len);
void pn_apply_values(PnScene *sc, const char *p);
void pn_apply_typed(PnScene *sc, PnNode *n, pn_u8 prop, char t, const char *v, pn_u32 len, int fromRow);
void pn_list_set_rows(PnScene *sc, PnList *L, pn_u32 nrows, const char *data);
PnList *pn_list_find(PnScene *sc, const char *name);
void pn_tokens_apply(PnScene *sc);
void pn_ramps_reset_scene(PnScene *sc);
PnTL *pn_tl_find(PnScene *sc, const char *name);
PnPaint *pn_paint_own(PnScene *sc, PnNode *n);

/* motion (pn_motion.c) */
float pn_ease(int e, float t);
int pn_ease_of(const char *s);
void pn_play(PnNode *n, PnTL *tl, double t0, float delay);
int pn_tl_eval(const PnTL *tl, double now, double t0, float delay, PnChans *out, int *done);
void pn_chans_identity(PnChans *c);
void pn_chans_mul(PnChans *acc, const PnChans *c);
void pn_scene_trigger(PnScene *sc, int trig, double t0);
void pn_scene_settle(PnScene *sc);
float pn_tl_length(const PnTL *tl, int nkids);

/* frame drawing (pn_draw.c) */
typedef struct { float a, bx, by; float rc, rs, rx, ry; } Xf; /* U = a*units + b; screen = R*U + t */
void pn_layout_scene(PnScene *sc, float w, float h, double now);
void pn_animate_scene(PnScene *sc, float dt, double now);
void pn_draw_scene(PnLayer *L, PnScene *sc, Xf xf, float alpha, int layerIndex, int interactive);
void pn_hits_reset(void);
int pn_tex_for_name(PnScene *sc, const char *name, pn_s32 id, int isNative);

/* input (pn_input.c) */
typedef struct { int layer; pn_s32 node; int row; pn_s32 list; float x0, y0, x1, y1; float rc, rs, rx, ry; } Hit;
void pn_add_hit(int layer, pn_s32 node, int row, pn_s32 list, float x0, float y0, float x1, float y1, const Xf *xf);
void pn_lists_step(PnScene *sc, float dt);
extern int pn_modal_floor;      /* hits below this layer index are ignored (modal) */

/* text */
int pn_font_find(const char *face);
int pn_font_ready(int f);
void pn_font_load_step(int f);
float pn_text_width(int f, const char *s, float px, int caps);
void pn_draw_text(PnNode *n, const char *text, float x, float y, float w, float h, float s, float alpha, const PnColor *col);
pn_u32 pn_utf8_next(const char **s);

/* assets */
int pn_read_asset(const char *rel, pn_u8 **data, pn_u32 *size);
int pn_asset_exists(const char *rel);
int pn_tex_load_step(int ti);
int pn_tex_waiting(void);   /* a texture on screen waits for a picture being made (keeps frames live) */
void pn_assets_gl_lost(void);
int pn_tex_find(const char *path);
int pn_tex_ready(int t);
void pn_tex_touch(int t);

/* renderer (all geometry in screen pixels) */
typedef struct { int shape; float hw, hh; float r[4]; const float *pts; int npts; } PrShape;
void pr_begin(int vw, int vh);
void pr_end(PnDrawSlotFn drawSlot);
void pr_set_texture(PnGLuint tex);
void pr_set_xform(float c, float s, float tx, float ty); /* screen = R * p + t for every vertex until reset */
void pr_fill(float cx, float cy, const PrShape *sh, const PnFill *fill, float alpha);
void pr_stroke(float cx, float cy, const PrShape *sh, const PnFill *fill, float width, float off, float alpha);
void pr_effect(float cx, float cy, const PrShape *sh, const PnFx *fx, int inner, float alpha);
void pr_ring(float cx, float cy, float R, float t, float start, float sweep, int cap, const PnFill *fill, const PnColor *solid, float alpha);
void pr_ring_glow(float cx, float cy, float R, float t, float start, float sweep, int cap, const PnFx *fx, float alpha);
void pr_star(float cx, float cy, float R, float rf, float clipX, const PnColor *c, float alpha);
void pr_band(float cx, float cy, float hw, float hh, float nx, float ny, float off, float halfw, const PnFill *fill, float alpha, int add);
void pr_image(float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, float radius, const PnColor *tint, float alpha, int mask);
void pr_glyph(float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, const PnColor *c, float factor, float bias, float alpha);
void pr_glass(float cx, float cy, const PrShape *sh, float radius, float alpha);
void pr_player(int slot, float x0, float y0, float x1, float y1);
void pr_clip(float x0, float y0, float x1, float y1, int on);
void pr_get_clip(float *c, int *on);
int pn_ramp_alloc(PnFill *f);
int pn_ramp_dynamic(PnFill *f);  /* a per-frame row for an animated gradient; -1 if none left */
void pr_upload_ramps(void);
PnGLuint pr_upload_rgba(int w, int h, const pn_u8 *rgba, PnGLuint reuse);
PnGLuint pr_upload_a8(int w, int h, const pn_u8 *a8);
void pr_delete_texture(PnGLuint t);
void pr_lost(void);
pn_u32 pr_gpu_bytes(void);          /* cached layer pictures + glass captures */
void pr_sweep(void);                /* free the pictures of layers that are gone (GL thread) */
void pr_release_all(void);          /* every Prism GL object back to the driver (GL thread) */
pn_u32 pn_assets_gpu_bytes(void);   /* decoded art + font atlases */
void pn_assets_gl_release(void);    /* art and fonts back to the driver; they reload on demand */
int pr_gl_ok(void);
int pr_gl_state(void);
#endif
