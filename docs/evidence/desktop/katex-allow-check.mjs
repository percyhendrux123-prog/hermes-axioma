import katex from '' + (process.env.HERMES_AGENT_DIR) + '/node_modules/katex/dist/katex.mjs'
const ranges = [[0x20,0x7e],[0xa0,0x24f],[0x2000,0x206f],[0x20a0,0x20bf],[0x2190,0x21ff]]
const excluded = new Set([0xa5,0x2028,0x2029,0x203c])
const esc = c => ({'\\':'\\textbackslash{}','{':'\\{','}':'\\}','$':'\\textdollar{}','%':'\\%','#':'\\#','&':'\\&','_':'\\_','^':'\\textasciicircum{}','~':'\\textasciitilde{}'}[c] ?? c)
const bodies = [t=>`\\color{#FF453A}{\\underline{\\textsf{\\textbf{${t}}}}}`, t=>`\\color{#FFCC00}{\\underline{\\textsf{${t}}}}`, t=>`\\color{#30D158}{\\textsf{\\textit{${t}}}}`, t=>`\\color{#EADFB8}{\\textsf{${t}}}`]
const bad = []; let n = 0
const origWarn = console.warn; console.warn = () => {}
for (const [a,b] of ranges) for (let c=a;c<=b;c++) { if (excluded.has(c)) continue; n++
  for (const f of bodies) { try { katex.renderToString(f('a'+esc(String.fromCodePoint(c))+'b'), {throwOnError:true}) } catch(e) { bad.push(c.toString(16)); break } } }
console.warn = origWarn
console.log('checked', n, 'bad', bad.length, bad.join(' '))
