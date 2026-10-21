"""Player Career: builds ux/flows/mainflow/gamemodes/Liga/Data/PrismProLook.lua from the game's files.

Create Your Player builds the face from the game's generic parts, the same ones a database player without his own
head model wears: a generic head mesh (data/sceneassets/heads/head_<type>_1.rx3), the face texture of the chosen
eyebrows / sideburns / facial hair / skin (faces/face_0_1_0_<brow>_<side>_<fhcolour>_<fhtype>_<skintype>_<tone>_
textures.rx3, a full grid in the OBB), the eyes (heads/eyes_<colour>_1_textures.rx3), a generic hairstyle
(hair/hair_<type>_1_0.rx3 + its textures) and boots (shoe/shoe_<type>.rx3 + textures). Only parts the OBB has are
offered, and only codes the database can hold: the same ranges libpv's writer (f16_pro.c COLS) accepts, within the
field's bit width in this database (the OBB has hairstyles 203..519; hairtypecode is 7 bits). The bodies are PrismYouth host players (leagues outside the career) that have an editedplayernames row, so the
created player's name is written into a row that exists.

inputs: an OBB file list (name<TAB>offset<TAB>size, both OBBs: tools/obb_list.py), the database, PrismYouthHosts.lua
usage: pro_look.py <obb list.tsv> <fifa_ng_db.db> <PrismYouthHosts.lua> <out PrismProLook.lua>
"""
import re, struct, sys

names = set(l.split('\t')[0] for l in open(sys.argv[1], encoding='latin1'))
db = open(sys.argv[2], 'rb').read()
size = len(db)
le32 = lambda o: struct.unpack_from('<I', db, o)[0]
le16 = lambda o: struct.unpack_from('<H', db, o)[0]


def hdr_ok(off):
    if off + 36 > size:
        return False
    rs, fc = le32(off + 4), le32(off + 24)
    if not rs or rs > 8192 or not fc or fc > 128 or off + 36 + fc * 16 > size:
        return False
    for i in range(fc):
        f = off + 36 + i * 16
        if le32(f) > 16 or any(not (65 <= db[f + k] <= 122) for k in range(8, 12)):
            return False
    return True


def tables():
    tc = le32(0x10)
    tn = [db[0x18 + i * 8:0x1c + i * 8].decode('latin1') for i in range(tc)]
    off, out = 0x18 + tc * 8 + 4, {}
    for t in range(tc):
        if not hdr_ok(off):
            break
        rs, written, fc, strl = le32(off + 4), le16(off + 18), le32(off + 24), le32(off + 12)
        fields = {db[off + 36 + i * 16 + 8:off + 36 + i * 16 + 12].decode('latin1'): (le32(off + 36 + i * 16 + 4), le32(off + 36 + i * 16 + 12)) for i in range(fc)}
        out[tn[t]] = (off + 36 + fc * 16, rs, written, fields)
        e = off + 36 + fc * 16 + written * rs + strl
        off = next((e + k for k in range(64) if hdr_ok(e + k)), None)
        if off is None:
            break
    return out


def bits(r, bo, depth):
    v = 0
    for i in range(depth):
        b = bo + i
        v |= ((r[b >> 3] >> (b & 7)) & 1) << i
    return v


T = tables()
pdata, prs, pn, PF = T['CZUM']
pids = set()
for i in range(pn):
    r = db[pdata + i * prs:pdata + (i + 1) * prs]
    if not r[-1] & 0x80:
        pids.add(bits(r, *PF['ykFq']))
ndata, nrs, nn, NF = T['nQVU']
named = set()
for i in range(nn):
    r = db[ndata + i * nrs:ndata + (i + 1) * nrs]
    if not r[-1] & 0x80:
        named.add(bits(r, *NF['ykFq']))


def ids(pat):
    return sorted(set(int(m.group(1)) for n in names for m in [re.match(pat, n)] if m))


heads = ids(r'data/sceneassets/heads/head_(\d+)_1\.rx3$')
hairs = sorted(set(ids(r'data/sceneassets/hair/hair_(\d+)_1_0\.rx3$')) & set(ids(r'data/sceneassets/hair/hair_(\d+)_1_textures\.rx3$')))
shoes = sorted(set(ids(r'data/sceneassets/shoe/shoe_(\d+)\.rx3$')) & set(ids(r'data/sceneassets/shoe/shoe_(\d+)_\d+_textures\.rx3$')))
eyes = ids(r'data/sceneassets/heads/eyes_(\d+)_1_textures\.rx3$')
grid = [tuple(map(int, m.groups())) for n in names for m in [re.match(r'data/sceneassets/faces/face_0_1_0_(\d+)_(\d+)_(\d+)_(\d+)_(\d+)_(\d+)_textures\.rx3$', n)] if m]
# brow, side, fhcolour, fhtype, skintype, tone: the values of the grid (a stray file - facial hair 9 in a single
# combination - is not one: a value needs at least half the files of the commonest); the grid must then be complete
import collections
axis = []
for i in range(6):
    c = collections.Counter(g[i] for g in grid)
    top = max(c.values())
    axis.append(sorted(v for v, k in c.items() if k * 2 >= top))
grid = [g for g in grid if all(g[i] in axis[i] for i in range(6))]
full = 1
for a in axis:
    full *= len(a)
have = set(grid)
import itertools
missing = [c for c in itertools.product(*axis) if c not in have]
assert not missing, 'the face grid has holes: %s' % missing[:5]
src = open(sys.argv[3], encoding='utf-8').read()
bodies = []
for club, s in re.findall(r'\[(\d+)\] = "([^"]*)"', src):
    for pid, _, _ in re.findall(r'(\d+)([a-zA-Z])(\d\d)', s):
        if int(pid) in named and int(pid) in pids:
            bodies.append('%s:%s' % (pid, club))


# the players-table field of each list and the range libpv's writer accepts (f16_pro.c COLS: keep the two the same)
RANGES = {'heads': ('OoQO', 0, 8000), 'hairs': ('CkYD', 0, 127), 'shoes': ('tgwT', 0, 1000), 'eyes': ('Zufj', 1, 16),
          'brows': ('HqUh', 0, 2), 'sideburns': ('mrAn', 0, 3), 'beardColours': ('mIlz', 0, 11), 'beards': ('onGA', 0, 19),
          'skinTypes': ('Dlgo', 0, 10), 'tones': ('ejir', 1, 11)}
dropped = {}


def fits(key, v):
    sn, lo, hi = RANGES[key]
    ok = lo <= v <= hi and v - lo < (1 << PF[sn][1])
    if not ok:
        dropped.setdefault(key, []).append(v)
    return ok


heads, hairs, shoes, eyes = ([v for v in l if fits(k, v)] for k, l in (('heads', heads), ('hairs', hairs), ('shoes', shoes), ('eyes', eyes)))
axis_keys = ('brows', 'sideburns', 'beardColours', 'beards', 'skinTypes', 'tones')
for i, k in enumerate(axis_keys):
    axis[i] = [v for v in axis[i] if fits(k, v)]
full = 1
for a in axis:
    full *= len(a)


def lst(v):
    return ', '.join(str(x) for x in v)


with open(sys.argv[4], 'w', encoding='utf-8') as o:
    o.write('-- PrismProLook - generated by tools/pro_look.py from the game\'s OBB file list and the user\'s database; do not edit by hand.\n--\n')
    o.write('-- What Create Your Player offers (PrismPro): the generic face parts the OBB has, and the bodies the created player can be.\n')
    o.write('--   heads %d, hairstyles %d, boots %d, eye colours %d; face textures: a full grid of %d (eyebrows x sideburns x facial hair colour x\n' % (len(heads), len(hairs), len(shoes), len(eyes), full))
    o.write('--   facial hair x skin type x skin tone); bodies: %d PrismYouth hosts with an editedplayernames row ("<player id>:<club id>").\n' % len(bodies))
    o.write('local T = {\n')
    o.write('  heads = { %s },\n' % lst(heads))
    o.write('  hairs = { %s },\n' % lst(hairs))
    o.write('  shoes = { %s },\n' % lst(shoes))
    o.write('  eyes = { %s },\n' % lst(eyes))
    for k, a in zip(axis_keys, axis):
        o.write('  %s = { %s },\n' % (k, lst(a)))
    o.write('  bodies = "%s",\n' % ' '.join(bodies))
    o.write('}\nrawset(_G, "PRISM_PRO_LOOK", T)\nreturn T\n')
print('dropped (the database cannot hold them):', dropped)
print('heads', len(heads), 'hairs', len(hairs), 'shoes', len(shoes), 'eyes', eyes, 'grid', full, 'axes', axis, 'bodies', len(bodies))
