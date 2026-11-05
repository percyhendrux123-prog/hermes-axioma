"""A229: CVD check of the plugin's four palettes with the spec's method (Machado 2009 + CIEDE2000)."""
import sys
sys.path.insert(0, '.')
from cvdlib import MACHADO, simulate, lab, de2000, contrast, hex2rgb
from axioma.signal import PALETTES
BG = {'dark': '#0E0F11', 'light': '#F6F5F1'}
for (theme, pal), colors in PALETTES.items():
    c = {k: '#' + v for k, v in colors.items()}
    print('== %s / %s (bg %s)' % (theme, pal, BG[theme]))
    for a, b in (('stop', 'caution'), ('stop', 'go'), ('caution', 'go'), ('caution', 'whisper')):
        row = {k: round(de2000(lab(simulate(c[a], k)), lab(simulate(c[b], k))), 1) for k in MACHADO}
        print('  %-17s %s' % (a + '/' + b, '  '.join('%s %5.1f' % (k[:6], v) for k, v in row.items())))
    print('  contrast: ' + ', '.join('%s %.1f:1' % (k, contrast(hex2rgb(v), hex2rgb(BG[theme]))) for k, v in c.items()))
