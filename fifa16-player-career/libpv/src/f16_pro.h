/* f16_pro.h - Player Career (PrismPro): the user's created player, his look and his name.

   Two parts:
   (1) The look in the 3D preview, at once: a per-player override of the appearance fields the preview resolves
       (f16_db_resolve_player applies it on top of the database row). Session memory only; Lua sends it again whenever
       the career binds. Set on the UI thread, read on the render workers: guarded by a spin lock.
   (2) The look, body and name in matches: the game reads its database from
       <root>/Android/data/com.ea.gp.fifaworld/data/db/fifa_ng_db.db when it starts (libfifa's own path; the OBB copy
       when there is no external one). The player's row of `players` (CZUM) and his row of `editedplayernames` (nQVU)
       are changed in place in that file: only bits inside existing records, the table's data CRC (CRC-32/MPEG-2 over
       its field descriptors and records, little-endian after them) put right, nothing grows or moves. Every table's
       CRC is checked before anything is written; the file is written the R86 way (f16_store_write_verified: tmp,
       fsync, rename, read back); the first change keeps the original as fifa_ng_db.db.pro-original.bak. The running
       game keeps the database it loaded: the change shows in matches from the next start.

   Commands (F16Service.Cmd "pro:..."; the reply is what Out() returns):
     pro:look:<pid>:<field>=<v>,...     preview override (replaces the player's earlier one)   "ok:<fields>"
     pro:look:<pid>:clear               no override                                             "ok:0"
     pro:db:<pid>:<field>=<v>,...       the database file's players row                         "ok:changed=<n>" | "ok:same" | "err:..."
     pro:name:<pid>:<first>|<surname>|<common>|<jersey>   his editedplayernames row            "ok:changed" | "ok:same" | "err:..."
     pro:get:<pid>                      the file's values: "<field>=<v>,...;first|surname|common|jersey" | "err:..."
     pro:caps                           "pro:1"
   Fields (the database's own names; values as the database means them, its range low included):
     hashighqualityhead headtypecode headclasscode eyebrowcode sideburnscode facialhaircolorcode facialhairtypecode
     skintypecode skintonecode eyecolorcode hairtypecode haircolorcode shoetypecode shoecolorcode1 shoecolorcode2
     height weight preferredfoot bodytypecode preferredposition1 */
#ifndef F16_PRO_H
#define F16_PRO_H
#include "preview_platform.h"
#include "f16_db.h"
#ifdef __cplusplus
extern "C" {
#endif

#define F16_PRO_NFIELDS 20
/* the field's index in the table above (0..F16_PRO_NFIELDS-1), -1 for an unknown name */
int f16_pro_field(const char *name, unsigned int len);
const char *f16_pro_field_name(int f);

/* (1) the preview: applies player `pid`'s override to a resolved row; 1 when there was one */
int f16_pro_apply(s32 pid, F16ResolvedPlayer *r);

/* (2) the database image in memory (the whole file): 0 ok, <0 error (why filled) */
int f16_pro_db_check(const u8 *db, u32 size, char *why, u32 whycap);
/* changes player `pid`'s fields (f[i] index, v[i] value): number of fields changed (0 = all already so), <0 error */
int f16_pro_db_set(u8 *db, u32 size, s32 pid, const int *f, const s32 *v, int n, char *why, u32 whycap);
/* his editedplayernames row: 1 changed, 0 already so, <0 error (no row: -2) */
int f16_pro_db_name(u8 *db, u32 size, s32 pid, const char *const names[4], char *why, u32 whycap);
/* his values and names as the pro:get reply */
int f16_pro_db_get(const u8 *db, u32 size, s32 pid, char *out, u32 cap);
u32 f16_pro_crc(const u8 *p, u32 n);   /* CRC-32/MPEG-2 (poly 0x04C11DB7, init ~0, no final xor) */

/* the router: one "pro:..." command; roots tried in order for the database file; reply(ctx, text, len) once */
void f16_pro_cmd(const char *const *roots, unsigned int nroots, const char *cmd,
                 void (*reply)(void *ctx, const char *s, unsigned int n), void *ctx);
/* tests: use this file instead of <root>/Android/data/.../fifa_ng_db.db (NULL: the roots) */
void f16_pro_set_db_path(const char *path);

#ifdef __cplusplus
}
#endif
#endif
