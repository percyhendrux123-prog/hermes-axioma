// Runs the plugin's Desktop output through Hermes Desktop's own render chain, as
// apps/desktop/src/components/assistant-ui/markdown-text.tsx does it: tailBoundedRemend(preprocessMarkdown(text)),
// then remark-math (singleDollarTextMath) and KaTeX. Written by the A229 pass-9 reviewer; remend
// step added after review pass 15. Usage (from <hermes-agent>/apps/desktop so tsx resolves '@/'):
//   HERMES_AGENT_DIR=/path/to/hermes-agent ../../node_modules/.bin/tsx desktop-pipeline-probe.mts cases.json
// Flags: KATEX_ERR (KaTeX refused), HREF! (a link inside math), JUNK! (remend's incomplete-link
// marker, or raw \color source, visible as text).
import { readFileSync } from 'node:fs'
const H = process.env.HERMES_AGENT_DIR
if (!H) throw new Error('set HERMES_AGENT_DIR')
const { preprocessMarkdown } = await import(H + '/apps/desktop/src/lib/markdown-preprocess.ts')
const { tailBoundedRemend } = await import(H + '/node_modules/@assistant-ui/react-streamdown/dist/remend.js')
const { unified } = await import(H + '/node_modules/unified/index.js')
const remarkParse = (await import(H + '/node_modules/remark-parse/index.js')).default
const remarkGfm = (await import(H + '/node_modules/remark-gfm/index.js')).default
const remarkMath = (await import(H + '/node_modules/remark-math/index.js')).default
const katex = (await import(H + '/node_modules/katex/dist/katex.mjs')).default
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'))
function walk(n: any, out: any[]) { if (n.type === 'inlineMath' || n.type === 'math') out.push(['MATH', n.value]); else if (n.type === 'text' || n.type === 'inlineCode') out.push([n.type, n.value]); for (const c of n.children || []) walk(c, out); return out }
for (const [k, v] of Object.entries(cases) as any) {
  const pre = tailBoundedRemend(preprocessMarkdown(v))
  const proc = unified().use(remarkParse).use(remarkGfm).use(remarkMath, { singleDollarTextMath: true })
  const nodes = walk(proc.runSync(proc.parse(pre)), [])
  console.log('==', k, '\n pre:', pre)
  for (const [t, val] of nodes) {
    let extra = ''
    if (t === 'MATH') { try { const h = katex.renderToString(val, { throwOnError: true }); extra = ' KATEX_OK' + (/href|<a /.test(h) ? ' HREF!' : '') } catch (e: any) { extra = ' KATEX_ERR ' + e.message.slice(0, 80) } }
    else if (t === 'text' && /streamdown:incomplete|\\color/.test(val)) extra = ' JUNK!'
    console.log('  ', t, JSON.stringify(val), extra)
  }
}
