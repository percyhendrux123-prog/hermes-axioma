"""Pass-20 Desktop cases: tags spliced across a span's styling, HTML blocks behind quote/list markers.
Run: python3 pass20-cases.py out.json, then feed out.json to desktop-pipeline-probe.mts."""
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from axioma.audit import Audit
from axioma.signal import Signal

cases = {
    'splice_across_bold': 'Run it [[signal:caution]signal:stop]now[/signal] please?',
    'splice_closer_across_bold': 'Run it [[signal:caution]/signal]now[/signal] please?',
    'splice_whisper_across_bold': 'Run it [[signal:stop]whisper:assumption]x[/signal] please?',
    'html_in_quote': '> <div> Do not run the [signal:stop]unsafe step[/signal] yet.',
    'html_in_list': '- <div>Do not run the [signal:stop]unsafe step[/signal] yet.</div>',
    'html_in_ordered_list': '1. <div>\n   Do not run the [signal:stop]unsafe step[/signal] yet.',
    'html_in_quoted_list': '> - <table>\n>   Do not run the [signal:stop]unsafe step[/signal] yet.',
    'math_control': 'Do not run the [signal:stop]unsafe step[/signal] yet.',
}
out = {}
for k, v in cases.items():
    s = Signal(Audit(Path(tempfile.mkdtemp()) / 'a.sqlite3'), env={})
    r = s.transform(v, session_id='d', platform='desktop', turn_id='t')
    out[k] = r if r is not None else v
json.dump(out, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
