/* f16_pro.c - Player Career: the created player's look (preview override) and his database row (see f16_pro.h). */
#include "preview_platform.h"
#include "f16_pro.h"
#include "f16_store.h"

/* ---- the fields: database name, players-table short name, range low and high (fifa_ng_db-meta.xml) */
typedef struct { const char *name; const char *shortn; s32 low, high; } ProCol;
static const ProCol COLS[F16_PRO_NFIELDS] = {
 {"hashighqualityhead","ykrW",0,1},{"headtypecode","OoQO",0,8000},{"headclasscode","HvCm",0,2},{"eyebrowcode","HqUh",0,2},
 {"sideburnscode","mrAn",0,3},{"facialhaircolorcode","mIlz",0,11},{"facialhairtypecode","onGA",0,19},{"skintypecode","Dlgo",0,10},
 {"skintonecode","ejir",1,11},{"eyecolorcode","Zufj",1,16},{"hairtypecode","CkYD",0,127},{"haircolorcode","uGEA",0,15},
 {"shoetypecode","tgwT",0,1000},{"shoecolorcode1","CSEx",0,31},{"shoecolorcode2","nbJH",0,31},{"height","ypBQ",150,215},
 {"weight","sNZW",50,115},{"preferredfoot","MDvm",1,2},{"bodytypecode","xWyx",1,32},{"preferredposition1","wZQU",0,31}};
enum { F_HQ, F_HEAD, F_CLASS, F_BROW, F_SIDE, F_FHC, F_FHT, F_SKINT, F_TONE, F_EYE, F_HAIR, F_HAIRC, F_SHOE, F_SHOE1,
       F_SHOE2, F_HEIGHT, F_WEIGHT, F_FOOT, F_BODY, F_POS };
/* editedplayernames' four names in the order pro:name takes them */
static const char *const NAME_COLS[4] = { "HdeP", "rREd", "xnfZ", "kRfb" };   /* first, surname, common, jersey */

static int streqn(const char *a, const char *b, unsigned int n){ for(unsigned int i=0;i<n;i++){ if(a[i]!=b[i]||!b[i]) return 0; } return b[n]==0; }
int f16_pro_field(const char *name, unsigned int len){
    for(int i=0;i<F16_PRO_NFIELDS;i++) if(streqn(name,COLS[i].name,len)) return i;
    return -1;
}
const char *f16_pro_field_name(int f){ return (f>=0&&f<F16_PRO_NFIELDS)?COLS[f].name:""; }

/* ---- (1) the preview override */
#define PRO_LOOKS 4
typedef struct { s32 pid; u32 mask; s32 v[F16_PRO_NFIELDS]; } ProLook;
static ProLook g_look[PRO_LOOKS];
static volatile int g_look_lock = 0;
static void look_lock(void){ while(__atomic_exchange_n(&g_look_lock,1,__ATOMIC_ACQUIRE)) usleep(20); }
static void look_unlock(void){ __atomic_store_n(&g_look_lock,0,__ATOMIC_RELEASE); }

int f16_pro_apply(s32 pid, F16ResolvedPlayer *r){
    if(pid<=0||!r) return 0;
    ProLook l; int found=0;
    look_lock();
    for(int i=0;i<PRO_LOOKS;i++) if(g_look[i].pid==pid&&g_look[i].mask){ l=g_look[i]; found=1; break; }
    look_unlock();
    if(!found) return 0;
#define SETF(f, dst) if(l.mask&(1u<<(f))) r->dst=l.v[f]
    SETF(F_HQ,hasHighQualityHead); SETF(F_HEAD,headType); SETF(F_CLASS,headClass); SETF(F_BROW,eyebrow);
    SETF(F_SIDE,sideburn); SETF(F_FHC,facialHairColor); SETF(F_FHT,facialHairType); SETF(F_SKINT,skinType);
    SETF(F_TONE,skinTone); SETF(F_EYE,eyeColor); SETF(F_HAIR,hairType); SETF(F_HAIRC,hairColor); SETF(F_SHOE,shoeType);
    SETF(F_SHOE1,shoeColor1); SETF(F_SHOE2,shoeColor2); SETF(F_POS,position);
#undef SETF
    return 1;
}
/* the player's 2D head pictures are kept per player id only: a new look needs them drawn again */
static void forget_head_pictures(s32 pid){
#ifndef F16_HOST
    char p[160];
    for(int k=1;k<=4;k++){ snprintf(p,sizeof(p),"/data/data/com.ea.gp.fifaworld/files/f16preview/heads/p%d_v%d.rgba",pid,k); unlink(p); }
#else
    (void)pid;
#endif
}
static int look_set(s32 pid, u32 mask, const s32 *v){
    int changed=1;
    look_lock();
    int at=-1;
    for(int i=0;i<PRO_LOOKS;i++) if(g_look[i].pid==pid){ at=i; break; }
    if(at<0) for(int i=0;i<PRO_LOOKS;i++) if(!g_look[i].mask){ at=i; break; }
    if(at<0) at=0;   /* full: the oldest place is reused */
    if(g_look[at].pid==pid&&g_look[at].mask==mask){
        changed=0;
        for(int f=0;f<F16_PRO_NFIELDS;f++) if((mask&(1u<<f))&&g_look[at].v[f]!=v[f]) changed=1;
    }
    g_look[at].pid=pid; g_look[at].mask=mask;
    for(int f=0;f<F16_PRO_NFIELDS;f++) g_look[at].v[f]=(mask&(1u<<f))?v[f]:0;
    look_unlock();
    if(changed) forget_head_pictures(pid);
    return changed;
}

/* ---- (2) the database image */
static u32 le32(const u8 *p){ return (u32)p[0]|((u32)p[1]<<8)|((u32)p[2]<<16)|((u32)p[3]<<24); }
static u16 le16(const u8 *p){ return (u16)(p[0]|(p[1]<<8)); }
static void wle32(u8 *p, u32 v){ p[0]=(u8)v; p[1]=(u8)(v>>8); p[2]=(u8)(v>>16); p[3]=(u8)(v>>24); }
static int eq4(const u8 *a, const char *b){ return a[0]==(u8)b[0]&&a[1]==(u8)b[1]&&a[2]==(u8)b[2]&&a[3]==(u8)b[3]; }

static u32 g_crct[256]; static int g_crc_ready=0;
u32 f16_pro_crc(const u8 *p, u32 n){
    if(!g_crc_ready){
        for(u32 i=0;i<256;i++){ u32 c=i<<24; for(int k=0;k<8;k++) c=(c&0x80000000u)?((c<<1)^0x04C11DB7u):(c<<1); g_crct[i]=c; }
        g_crc_ready=1;
    }
    u32 c=0xFFFFFFFFu;
    for(u32 i=0;i<n;i++) c=g_crct[((c>>24)^p[i])&0xFFu]^(c<<8);
    return c;
}

/* A table: header (36 bytes: +4 record size, +12 string block bytes, +18 rows written, +24 field count, +32 header
   CRC), field descriptors (16 bytes: type, bit offset, short name, bit depth), records, string block, data CRC. */
typedef struct { u32 off, rs, written, fc, strl, data, end; } PTable;
static int hdr_ok(const u8 *db, u32 size, u32 off){
    if((u64)off+36>size) return 0;
    u32 rs=le32(db+off+4), fc=le32(db+off+24);
    if(!rs||rs>8192||!fc||fc>128||(u64)off+36+(u64)fc*16>size) return 0;
    for(u32 i=0;i<fc;i++){ const u8 *f=db+off+36+i*16; if(le32(f)>16) return 0; for(int k=8;k<12;k++) if(f[k]<'A'||f[k]>'z') return 0; }
    return 1;
}
static int table_at(const u8 *db, u32 size, u32 off, PTable *t){
    if(!hdr_ok(db,size,off)) return 0;
    t->off=off; t->rs=le32(db+off+4); t->strl=le32(db+off+12); t->written=le16(db+off+18); t->fc=le32(db+off+24);
    t->data=off+36+t->fc*16;
    u64 e=(u64)t->data+(u64)t->written*t->rs+t->strl;
    if(e+4>size) return 0;
    t->end=(u32)e;
    return 1;
}
/* walks the tables in order (an edited database can keep stale directory offsets, as f16_db.c knows) */
static int find_table(const u8 *db, u32 size, const char *shortn, PTable *out){
    if(size<0x40||db[0]!='D'||db[1]!='B') return 0;
    u32 tc=le32(db+0x10); if(tc==0||tc>1000) return 0;
    u32 off=0x18+tc*8+4;
    for(u32 i=0;i<tc;i++){
        PTable t; if(!table_at(db,size,off,&t)) return 0;
        if(eq4(db+0x18+i*8,shortn)){ *out=t; return 1; }
        u32 nx=0; for(u32 d=0;d<64&&t.end+d<size;d++) if(hdr_ok(db,size,t.end+d)){ nx=t.end+d; break; }
        if(!nx) return 0;
        off=nx;
    }
    return 0;
}
static int field_of(const u8 *db, const PTable *t, const char *shortn, u32 *bitoff, u32 *depth, u32 *type){
    for(u32 i=0;i<t->fc;i++){ const u8 *f=db+t->off+36+i*16; if(eq4(f+8,shortn)){ *type=le32(f); *bitoff=le32(f+4); *depth=le32(f+12); return 1; } }
    return 0;
}
static u32 get_bits(const u8 *r, u32 off, u32 n){ u32 v=0; for(u32 i=0;i<n&&i<32;i++) v|=(u32)((r[(off+i)>>3]>>((off+i)&7))&1u)<<i; return v; }
static void put_bits(u8 *r, u32 off, u32 n, u32 v){ for(u32 i=0;i<n&&i<32;i++){ u8 m=(u8)(1u<<((off+i)&7)); if((v>>i)&1u) r[(off+i)>>3]|=m; else r[(off+i)>>3]&=(u8)~m; } }
static int crc_ok(const u8 *db, const PTable *t){ return f16_pro_crc(db+t->off+36,t->end-(t->off+36))==le32(db+t->end); }
static void crc_fix(u8 *db, const PTable *t){ wle32(db+t->end,f16_pro_crc(db+t->off+36,t->end-(t->off+36))); }
/* the row of player `pid` in a table with a playerid field */
static u8 *row_of(const u8 *db, const PTable *t, s32 pid){
    u32 bo,dp,ty; if(!field_of(db,t,"ykFq",&bo,&dp,&ty)||ty!=3) return 0;
    for(u32 i=0;i<t->written;i++){
        const u8 *r=db+t->data+i*t->rs;
        if(r[t->rs-1]&0x80) continue;   /* a deleted row */
        if((s32)get_bits(r,bo,dp)==pid) return (u8*)r;
    }
    return 0;
}
#define WHY(...) do{ if(why&&whycap) snprintf(why,whycap,__VA_ARGS__); }while(0)

int f16_pro_db_check(const u8 *db, u32 size, char *why, u32 whycap){
    PTable p, n;
    if(!find_table(db,size,"CZUM",&p)){ WHY("no players table (CZUM)"); return -1; }
    if(!crc_ok(db,&p)){ WHY("the players table's CRC is not the one this writer knows"); return -2; }
    if(find_table(db,size,"nQVU",&n)&&!crc_ok(db,&n)){ WHY("the editedplayernames table's CRC is not the one this writer knows"); return -3; }
    return 0;
}
int f16_pro_db_set(u8 *db, u32 size, s32 pid, const int *f, const s32 *v, int n, char *why, u32 whycap){
    PTable t;
    if(!find_table(db,size,"CZUM",&t)){ WHY("no players table (CZUM)"); return -1; }
    if(!crc_ok(db,&t)){ WHY("the players table's CRC is not the one this writer knows"); return -2; }
    u8 *r=row_of(db,&t,pid); if(!r){ WHY("player %d is not in the players table",pid); return -3; }
    /* every field is checked before anything changes */
    u32 bo[F16_PRO_NFIELDS], dp[F16_PRO_NFIELDS], raw[F16_PRO_NFIELDS];
    for(int i=0;i<n;i++){
        if(f[i]<0||f[i]>=F16_PRO_NFIELDS){ WHY("unknown field"); return -4; }
        u32 ty; if(!field_of(db,&t,COLS[f[i]].shortn,&bo[i],&dp[i],&ty)||ty!=3){ WHY("no integer column %s",COLS[f[i]].name); return -5; }
        s64 x=(s64)v[i]-COLS[f[i]].low;
        if(v[i]<COLS[f[i]].low||v[i]>COLS[f[i]].high||dp[i]>31||x>=((s64)1<<dp[i])){ WHY("%s=%d is outside %d..%d",COLS[f[i]].name,v[i],COLS[f[i]].low,COLS[f[i]].high); return -6; }
        raw[i]=(u32)x;
    }
    int changed=0;
    for(int i=0;i<n;i++) if(get_bits(r,bo[i],dp[i])!=raw[i]){ put_bits(r,bo[i],dp[i],raw[i]); changed++; }
    if(changed) crc_fix(db,&t);
    return changed;
}
static int name_ok(const char *s){ for(;*s;s++){ unsigned char c=(unsigned char)*s; if(c<0x20||c==0x7f||c=='|') return 0; } return 1; }
int f16_pro_db_name(u8 *db, u32 size, s32 pid, const char *const names[4], char *why, u32 whycap){
    PTable t;
    if(!find_table(db,size,"nQVU",&t)){ WHY("no editedplayernames table (nQVU)"); return -1; }
    if(!crc_ok(db,&t)){ WHY("the editedplayernames table's CRC is not the one this writer knows"); return -3; }
    u8 *r=row_of(db,&t,pid); if(!r){ WHY("player %d has no editedplayernames row",pid); return -2; }
    u32 bo[4], dp[4];
    for(int i=0;i<4;i++){
        u32 ty; if(!field_of(db,&t,NAME_COLS[i],&bo[i],&dp[i],&ty)||ty!=0||(bo[i]&7)||(dp[i]&7)){ WHY("editedplayernames column %.4s is not a byte string",NAME_COLS[i]); return -4; }
        unsigned int L=(unsigned int)strlen(names[i]?names[i]:"");
        if(!names[i]||L+1>dp[i]/8||!name_ok(names[i])){ WHY("name %d does not fit (%u bytes, %u)",i+1,L,dp[i]/8-1); return -5; }
    }
    int changed=0;
    for(int i=0;i<4;i++){
        u8 *s=r+bo[i]/8; u32 cap=dp[i]/8; unsigned int L=(unsigned int)strlen(names[i]);
        for(u32 k=0;k<cap;k++){ u8 c=k<L?(u8)names[i][k]:0; if(s[k]!=c){ s[k]=c; changed=1; } }
    }
    if(changed) crc_fix(db,&t);
    return changed;
}
int f16_pro_db_get(const u8 *db, u32 size, s32 pid, char *out, u32 cap){
    PTable t; u32 o=0;
    if(!out||!cap) return -1;
    out[0]=0;
    if(!find_table(db,size,"CZUM",&t)){ snprintf(out,cap,"err:no players table"); return -1; }
    const u8 *r=row_of(db,&t,pid); if(!r){ snprintf(out,cap,"err:player %d is not in the players table",pid); return -2; }
    for(int i=0;i<F16_PRO_NFIELDS;i++){
        u32 bo,dp,ty; if(!field_of(db,&t,COLS[i].shortn,&bo,&dp,&ty)) continue;
        int w=snprintf(out+o,cap-o,"%s%s=%d",o?",":"",COLS[i].name,(int)((s64)get_bits(r,bo,dp)+COLS[i].low));
        if(w<0||o+(u32)w>=cap) return -3;
        o+=(u32)w;
    }
    PTable nt; const u8 *nr=find_table(db,size,"nQVU",&nt)?row_of(db,&nt,pid):0;
    for(int i=0;i<4;i++){
        char s[64]; s[0]=0;
        u32 bo,dp,ty;
        if(nr&&field_of(db,&nt,NAME_COLS[i],&bo,&dp,&ty)&&ty==0&&!(bo&7)){ u32 L=dp/8<63?dp/8:63; memcpy(s,nr+bo/8,L); s[L]=0; }
        int w=snprintf(out+o,cap-o,"%s%s",i==0?";":"|",s);
        if(w<0||o+(u32)w>=cap) return -3;
        o+=(u32)w;
    }
    return 0;
}

/* ---- the file */
static char g_test_path[512];
void f16_pro_set_db_path(const char *path){ g_test_path[0]=0; if(path) snprintf(g_test_path,sizeof(g_test_path),"%s",path); }
static int read_all(const char *path, u8 **out, u32 *n){
    int fd=open(path,O_RDONLY); if(fd<0) return 0;
    off_t sz=lseek(fd,0,2); if(sz<=0||sz>64*1024*1024){ close(fd); return 0; }
    lseek(fd,0,0);
    u8 *b=(u8*)malloc((size_t)sz); if(!b){ close(fd); return 0; }
    u32 got=0; while(got<(u32)sz){ ssize_t r=read(fd,b+got,(size_t)((u32)sz-got)); if(r<=0) break; got+=(u32)r; }
    close(fd);
    if(got!=(u32)sz){ free(b); return 0; }
    *out=b; *n=got; return 1;
}
static int exists(const char *p){ int fd=open(p,O_RDONLY); if(fd<0) return 0; close(fd); return 1; }
/* the database file: the test's, else the first root that has one */
static int db_path(const char *const *roots, unsigned int nroots, char *path, u32 cap){
    if(g_test_path[0]){ snprintf(path,cap,"%s",g_test_path); return exists(path); }
    for(unsigned int i=0;i<nroots;i++){
        snprintf(path,cap,"%s/Android/data/com.ea.gp.fifaworld/data/db/fifa_ng_db.db",roots[i]);
        if(exists(path)) return 1;
    }
    return 0;
}
static int parse_i(const char *s, s32 *out, const char **end){
    int neg=0; s64 v=0; int any=0;
    if(*s=='-'){ neg=1; s++; }
    while(*s>='0'&&*s<='9'){ v=v*10+(*s-'0'); s++; any=1; if(v>0x7fffffffLL) v=0x7fffffffLL; }
    if(end)*end=s;
    if(!any) return 0;
    *out=(s32)(neg?-v:v); return 1;
}
/* "<field>=<v>,..." -> indices, values, mask; 0 on a bad list (why filled) */
static int parse_fields(const char *p, int *f, s32 *v, int *n, u32 *mask, char *why, u32 whycap){
    *n=0; *mask=0;
    while(*p){
        const char *eq=p; while(*eq&&*eq!='='&&*eq!=',') eq++;
        if(*eq!='='){ WHY("bad field list"); return 0; }
        int fi=f16_pro_field(p,(unsigned int)(eq-p));
        if(fi<0){ WHY("unknown field %.*s",(int)(eq-p),p); return 0; }
        s32 val; const char *e;
        if(!parse_i(eq+1,&val,&e)){ WHY("bad value for %s",COLS[fi].name); return 0; }
        if(*n>=F16_PRO_NFIELDS){ WHY("too many fields"); return 0; }
        f[*n]=fi; v[*n]=val; (*n)++; *mask|=1u<<fi;
        if(*e==','){ p=e+1; continue; }
        if(*e==0) break;
        WHY("bad separator"); return 0;
    }
    return 1;
}
static void say(void (*reply)(void*,const char*,unsigned int), void *ctx, const char *s){ reply(ctx,s,(unsigned int)strlen(s)); }

void f16_pro_cmd(const char *const *roots, unsigned int nroots, const char *cmd,
                 void (*reply)(void *ctx, const char *s, unsigned int n), void *ctx){
    char why[200]; why[0]=0;
    char b[600];
    const char *p=cmd+4;   /* after "pro:" */
    if(!strcmp(p,"caps")){ say(reply,ctx,"pro:1"); return; }
    int look=0, set=0, name=0, get=0;
    if(!memcmp(p,"look:",5)){ look=1; p+=5; }
    else if(!memcmp(p,"db:",3)){ set=1; p+=3; }
    else if(!memcmp(p,"name:",5)){ name=1; p+=5; }
    else if(!memcmp(p,"get:",4)){ get=1; p+=4; }
    else { say(reply,ctx,"err:unknown pro command"); return; }
    s32 pid=0; const char *e;
    if(!parse_i(p,&pid,&e)||pid<=0||(*e!=':'&&!(get&&*e==0))){ say(reply,ctx,"err:bad playerid"); return; }
    p=*e==':'?e+1:e;
    int f[F16_PRO_NFIELDS]; s32 v[F16_PRO_NFIELDS]; int n=0; u32 mask=0;
    if(look){
        s32 all[F16_PRO_NFIELDS]; memset(all,0,sizeof(all));
        if(!strcmp(p,"clear")){ look_set(pid,0,all); say(reply,ctx,"ok:0"); return; }
        if(!parse_fields(p,f,v,&n,&mask,why,sizeof(why))){ snprintf(b,sizeof(b),"err:%s",why); say(reply,ctx,b); return; }
        for(int i=0;i<n;i++) all[f[i]]=v[i];
        look_set(pid,mask,all);
        snprintf(b,sizeof(b),"ok:%d",n); say(reply,ctx,b); return;
    }
    const char *names[4]={0,0,0,0}; char nb[4][64];
    if(set&&!parse_fields(p,f,v,&n,&mask,why,sizeof(why))){ snprintf(b,sizeof(b),"err:%s",why); say(reply,ctx,b); return; }
    if(name){
        for(int i=0;i<4;i++){
            const char *q=p; while(*q&&*q!='|') q++;
            unsigned int L=(unsigned int)(q-p); if(L>=sizeof(nb[i])){ say(reply,ctx,"err:name too long"); return; }
            memcpy(nb[i],p,L); nb[i][L]=0; names[i]=nb[i];
            if(i<3){ if(*q!='|'){ say(reply,ctx,"err:name expects first|surname|common|jersey"); return; } p=q+1; }
            else if(*q){ say(reply,ctx,"err:name expects first|surname|common|jersey"); return; }
        }
    }
    static const char *const fallback[]={ "/storage/emulated/0", "/sdcard" };
    if(!roots||!nroots){ roots=fallback; nroots=2; }
    char path[560];
    if(!db_path(roots,nroots,path,sizeof(path))){ say(reply,ctx,"err:no database file at Android/data/com.ea.gp.fifaworld/data/db/fifa_ng_db.db"); return; }
    u8 *db=0; u32 size=0;
    if(!read_all(path,&db,&size)){ say(reply,ctx,"err:cannot read the database file"); return; }
    if(get){
        char *o=(char*)malloc(2048);
        if(o){ f16_pro_db_get(db,size,pid,o,2048); say(reply,ctx,o); free(o); } else say(reply,ctx,"err:out of memory");
        free(db); return;
    }
    if(f16_pro_db_check(db,size,why,sizeof(why))<0){ snprintf(b,sizeof(b),"err:%s",why); say(reply,ctx,b); free(db); return; }
    u8 *orig=(u8*)malloc(size);
    if(orig) memcpy(orig,db,size);
    int r=set?f16_pro_db_set(db,size,pid,f,v,n,why,sizeof(why)):f16_pro_db_name(db,size,pid,names,why,sizeof(why));
    if(r<0){ snprintf(b,sizeof(b),"err:%s",why); say(reply,ctx,b); free(db); if(orig) free(orig); return; }
    if(r==0){ say(reply,ctx,"ok:same"); free(db); if(orig) free(orig); return; }
    /* the original once, then the file the R86 way */
    char bak[600]; snprintf(bak,sizeof(bak),"%s.pro-original.bak",path);
    if(orig&&!exists(bak)&&!f16_store_write_verified(bak,orig,size)){ say(reply,ctx,"err:cannot keep the original (storage full?)"); free(db); free(orig); return; }
    if(orig) free(orig);
    if(!f16_store_write_verified(path,db,size)){ say(reply,ctx,"err:the database file could not be written (storage full?)"); free(db); return; }
    free(db);
    if(set){ snprintf(b,sizeof(b),"ok:changed=%d",r); say(reply,ctx,b); }
    else say(reply,ctx,"ok:changed");
}
