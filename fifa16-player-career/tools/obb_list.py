"""Lists a BIG4 archive (the game's OBB): one "name<TAB>offset<TAB>size" line per file. Reads only the header and the
file table, so the first ~1.2 MB of the OBB is enough. usage: obb_list.py <obb or its first MB> [...] > list.tsv"""
import struct, sys
for path in sys.argv[1:]:
    d = open(path, 'rb').read(4 * 1024 * 1024)
    assert d[:4] == b'BIG4', path
    n = struct.unpack('>I', d[8:12])[0]
    p = 16
    for _ in range(n):
        off, size = struct.unpack('>II', d[p:p + 8])
        e = d.index(b'\0', p + 8)
        print('%s\t%d\t%d' % (d[p + 8:e].decode('latin1').replace('\\', '/'), off, size))
        p = e + 1
