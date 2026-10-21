"""Player Career: patches the Popup scene (ux/prism/skins/Popup.pn) for Create Your Player.

The Career Setup screen (csscreen) doubles as Create Your Player (PrismPro.open). This adds, idempotently:
  * the header and the two button labels as bindings (bnd_cs_hdr, bnd_cs_go, bnd_cs_rst; the static text stays as the
    fallback until the first publish),
  * the info panel shown only for Career Setup (bnd_cs_std) and a narrow copy of it shown only for Create Your Player
    (infopro, bnd_cs_pro),
  * the 3D model's place, slot 4 (cs_player3d_4, bnd_cs_pro): pn_scene draws a slot where a node named *_player3d_N is.
The file is written back byte-compatible (compact JSON, UTF-8 as is). usage: pro_popup_pn.py <Popup.pn>
"""
import copy, json, sys

path = sys.argv[1]
d = json.loads(open(path, encoding='utf-8').read())


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


cs = find(d['root'], lambda n: n.get('name') == 'csscreen')
assert cs, 'no csscreen'
bind(find(cs, lambda n: n.get('name') == 'hdr_title'), 'bnd_cs_hdr', 'text')
content = find(cs, lambda n: n.get('name') == 'cscontent')
start = find(content, lambda n: any(b.get('binding') == 'pv33' for b in n.get('bindings') or []))
bind(find(start, lambda n: n.get('commonName') == 'Label'), 'bnd_cs_go', 'text')
hint2 = find(cs, lambda n: n.get('name') == 'hint2')
bind(find(hint2, lambda n: n.get('commonName') == 'Label'), 'bnd_cs_rst', 'text')

info = find(content, lambda n: n.get('name') == 'info')
bind(info, 'bnd_cs_std', 'visible')
kids = content['children']
if not any(c.get('name') == 'infopro' for c in kids):
    pro = copy.deepcopy(info)
    pro['name'] = 'infopro'
    pro['bindings'] = [{'binding': 'bnd_cs_pro', 'property': 'visible'}]
    for k in ('marginRight',):
        pro.pop(k, None)
    pro['alignH'] = 'LEFT'
    pro['width'] = 290.37
    pro['height'] = 345.48
    for lab in pro['children']:
        if lab.get('multiline'):
            lab['maxLines'] = 16
    kids.insert(kids.index(info) + 1, pro)
if not any(c.get('name') == 'cs_player3d_4' for c in kids):
    kids.append({'commonName': 'Panel', 'name': 'cs_player3d_4', 'alignH': 'LEFT', 'marginLeft': 871.11, 'width': 266.67,
                 'alignV': 'TOP', 'marginTop': 94.81, 'height': 486.52,
                 'bindings': [{'binding': 'bnd_cs_pro', 'property': 'visible'}]})

open(path, 'w', encoding='utf-8').write(json.dumps(d, separators=(',', ':'), ensure_ascii=False))
print('Popup.pn patched for Create Your Player')
