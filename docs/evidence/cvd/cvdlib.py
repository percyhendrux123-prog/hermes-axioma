"""Color-vision-deficiency check for Axioma signal palettes. Stdlib only.

Method: Machado, Oliveira & Fernandes (2009), severity 1.0 matrices applied in
linear sRGB; colour difference by CIEDE2000; contrast by WCAG 2.x relative luminance.
Run: python3 cvd_check.py
"""
import math

MACHADO = {
    'normal': [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    'protanopia': [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    'deuteranopia': [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    'tritanopia': [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}

PALETTES = {
    'axioma-night (bg #0E0F11)': {'bg': '#0E0F11', 'stop': '#FF453A', 'caution': '#FFCC00', 'go': '#30D158', 'whisper': '#EADFB8', 'text': '#F0F0EE'},
    'axioma-day (bg #F6F5F1)': {'bg': '#F6F5F1', 'stop': '#D70015', 'caution': '#A66B00', 'go': '#248A3D', 'whisper': '#8A6A1F', 'text': '#1A1B1E'},
    'okabe-ito alt night': {'bg': '#0E0F11', 'stop': '#E8603C', 'caution': '#F0E442', 'go': '#56B4E9', 'whisper': '#EADFB8', 'text': '#F0F0EE'},
}


def hex2rgb(h):
    h = h.lstrip('#')
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def delin(c):
    c = min(max(c, 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def simulate(h, kind):
    l = [lin(c) for c in hex2rgb(h)]
    m = MACHADO[kind]
    return [delin(sum(m[i][j] * l[j] for j in range(3))) for i in range(3)]


def lab(rgb):
    r, g, b = [lin(c) for c in rgb]
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b)
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def de2000(l1, l2):
    L1, a1, b1 = l1
    L2, a2, b2 = l2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    if C1p * C2p == 0:
        dh = 0
    elif dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    else:
        hbp = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dtheta = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dtheta)) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def lum(rgb):
    r, g, b = [lin(c) for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(c1, c2):
    a, b = sorted([lum(c1), lum(c2)], reverse=True)
    return (a + 0.05) / (b + 0.05)


PAIRS = [('stop', 'caution'), ('stop', 'go'), ('caution', 'go'), ('whisper', 'text'), ('caution', 'whisper')]

