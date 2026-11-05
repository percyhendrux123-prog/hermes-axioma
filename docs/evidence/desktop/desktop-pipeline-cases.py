import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from axioma.audit import Audit
from axioma.signal import Signal
def sig(**kw):
    return Signal(Audit(Path(tempfile.mkdtemp()) / 'a.sqlite3'), env={}, **kw)
cases = {
 'percy': 'I can, but shipping [signal:stop;why=x]without an eval or a test[/signal] means the [signal:caution]merge into Hermes[/signal] lands under your name?',
 'dollar_before': 'It costs $[whisper:unverified_figure]4,200[/whisper] a month.',
 'cjk_span': '请 [signal:stop;why=x]不要删除[/signal] 好吗?',
 'cjk_prose_around': '价格 $5 和 [signal:caution]rises[/signal] 然后 [signal:stop;why=x]halt[/signal] ok',
 'backslash_before': 'Path C:\\[signal:stop;why=x]Windows[/signal] gone?',
 'fullwidth': 'Note [signal:caution]a，b[/signal] here?',
 'currency_after': 'x [signal:caution]rises[/signal] then $5 and $10 later',
 'currency_before': 'costs $5 and [signal:caution]x[/signal] then $10?',
 'lone_dollar_earlier': 'It costs 5$ and [signal:caution]x[/signal] now?',
 'special': '[signal:caution]a $5 {b} \\c %d #e &f _g ^h ~i[/signal] ok',
 'two_on_line': '[signal:stop;why=x]alpha[/signal] and [signal:caution]beta[/signal] and [whisper:assumption]gamma[/whisper].',
 'go_digit_after': 'The suite [signal:go;check=terminal]passed 114 of 114[/signal]. Fine.',
}
out = {}
for k, v in cases.items():
    s = sig()
    s.observe(tool_name='terminal', tool_call_id='c', session_id='d', turn_id='t', status='ok')
    out[k] = s.transform(v, session_id='d', platform='desktop', turn_id='t')
for k, v in {'plain_adjacent': 'a [signal:stop;why=x]x[/signal][signal:caution]b[/signal] c?',
             'plain_digit_after': '[signal:caution]x[/signal]5 units?',
             'plain_ok': 'a [signal:caution]x[/signal], fine?'}.items():
    out[k] = sig(words='plain_only').transform(v, session_id='d', platform='desktop')
json.dump(out, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
