import colorsys
from cvdlib import *
bg='#F6F5F1'
def hx(r,g,b): return '#%02X%02X%02X'%(round(r*255),round(g*255),round(b*255))
def C(h,l,s): return hx(*colorsys.hls_to_rgb(h/360,l,s))
def ok(c): return contrast(hex2rgb(c),hex2rgb(bg))>=4.5
def score(a,b): return min(de2000(lab(simulate(a,k)),lab(simulate(b,k))) for k in MACHADO)
stops=[C(h,l,s) for h in list(range(348,360,4))+list(range(0,16,4)) for l in [.36,.38,.40,.42,.44] for s in [.8,.9,1]]
cauts=[C(h,l,s) for h in range(30,52,3) for l in [.22,.25,.28,.31] for s in [.7,.85,1]]
gos=[C(h,l,s) for h in range(195,225,5) for l in [.28,.32,.36,.40] for s in [.7,.85,1]]
stops=[c for c in stops if ok(c)];cauts=[c for c in cauts if ok(c)];gos=[c for c in gos if ok(c)]
best=None
for s in stops:
  for c in cauts:
    sc=score(s,c)
    if best and sc<best[0]: continue
    for g in gos:
      m=min(sc,score(s,g),score(c,g))
      if not best or m>best[0]: best=(m,s,c,g)
print(best)
m,s,c,g=best
for a,b in [(s,c),(s,g),(c,g)]:
  print(a,b,{k:round(de2000(lab(simulate(a,k)),lab(simulate(b,k))),1) for k in MACHADO})
for x in (s,c,g,'#8A6A1F'): print(x, round(contrast(hex2rgb(x),hex2rgb(bg)),2))
