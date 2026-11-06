"""Player Career: patches the two Prism scenes Create Your Player uses. Idempotent; run on a fresh R98e ux or again.

ux/prism/skins/Popup.pn - the Career Setup screen (csscreen) doubles as Create Your Player (PrismPro.open):
  * the header and the two button labels become bindings (bnd_cs_hdr, bnd_cs_go, bnd_cs_rst; the static text stays as
    the fallback until the first publish),
  * the info panel shows only for Career Setup (bnd_cs_std); a narrow copy shows only for Create Your Player (infopro,
    bnd_cs_pro),
  * the 3D model's two places, both slot 4 (pn_scene draws a slot where a node named *_player3d_N is): the whole player
    on the player page (cs_player3d_4, bnd_cs_body) and head and shoulders on the face page (csface_player3d_4,
    bnd_cs_face).
ux/prism/skins/Keyboard.pn - the career keyboard doubles as the name entry (Liga/Screens/ProName):
  * its crumb and title become bindings (bnd_kb_crumb, bnd_kb_title), the static texts the fallback.
Both files are written back byte-compatible (compact JSON, UTF-8 as is). usage: pro_scenes.py <ux dir>
"""
import copy, json, os, sys

ux = sys.argv[1]


def load(p):
    return json.loads(open(p, encoding='utf-8').read())


def save(p, d):
    open(p, 'w', encoding='utf-8').write(json.dumps(d, separators=(',', ':'), ensure_ascii=False))


def find(n, pred):
    if pred(n):
        return n
    for c in n.get('children') or []:
        r = find(c, pred)
        if r:
            return r
    return None


def bind(node, name, prop):
    bs = node.setdefault('bindings', [])
    if not any(b.get('binding') == name and b.get('property') == prop for b in bs):
        bs.append({'binding': name, 'property': prop})


# ---- Popup.pn
p = os.path.join(ux, 'prism/skins/Popup.pn')
d = load(p)
cs = find(d['root'], lambda n: n.get('name') == 'csscreen')
assert cs, 'no csscreen'
bind(find(cs, lambda n: n.get('name') == 'hdr_title'), 'bnd_cs_hdr', 'text')
content = find(cs, lambda n: n.get('name') == 'cscontent')
start = find(content, lambda n: any(b.get('binding') == 'pv33' for b in n.get('bindings') or []))
bind(find(start, lambda n: n.get('commonName') == 'Label'), 'bnd_cs_go', 'text')
bind(find(find(cs, lambda n: n.get('name') == 'hint2'), lambda n: n.get('commonName') == 'Label'), 'bnd_cs_rst', 'text')
info = find(content, lambda n: n.get('name') == 'info')
bind(info, 'bnd_cs_std', 'visible')
kids = content['children']
if not any(c.get('name') == 'infopro' for c in kids):
    pro = copy.deepcopy(info)
    pro['name'] = 'infopro'
    pro['bindings'] = [{'binding': 'bnd_cs_pro', 'property': 'visible'}]
    pro.pop('marginRight', None)
    pro['alignH'], pro['width'], pro['height'] = 'LEFT', 290.37, 345.48
    for lab in pro['children']:
        if lab.get('multiline'):
            lab['maxLines'] = 16
    kids.insert(kids.index(info) + 1, pro)
for name, geo, b in (('cs_player3d_4', (871.11, 266.67, 94.81, 486.52), 'bnd_cs_body'),
                     ('csface_player3d_4', (853.33, 331.85, 71.11, 1066.67), 'bnd_cs_face')):
    node = next((c for c in kids if c.get('name') == name), None)
    if node is None:
        node = {'commonName': 'Panel', 'name': name}
        kids.append(node)
    node.update({'alignH': 'LEFT', 'marginLeft': geo[0], 'width': geo[1], 'alignV': 'TOP', 'marginTop': geo[2], 'height': geo[3],
                 'bindings': [{'binding': b, 'property': 'visible'}]})
save(p, d)

# ---- Keyboard.pn
p = os.path.join(ux, 'prism/skins/Keyboard.pn')
d = load(p)
bind(find(d['root'], lambda n: n.get('name') == 'hdr_crumb'), 'bnd_kb_crumb', 'text')
bind(find(d['root'], lambda n: n.get('name') == 'hdr_title'), 'bnd_kb_title', 'text')
save(p, d)
print('Popup.pn and Keyboard.pn patched for Create Your Player')
