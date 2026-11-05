"""Pass-19 Desktop cases: tags spliced by removal, and intent bold next to punctuation.
Run: python3 pass19-cases.py out.json, then feed out.json to desktop-pipeline-probe.mts."""
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from axioma.audit import Audit
from axioma.signal import Signal

cases = {
    'splice_closer': 'ok [[/signal]/signal] done',
    'splice_used_opener': 'Real [signal:stop]a[/signal] then [[/signal]signal:stop]x',
    'splice_used_go': 'x [signal:go;check=terminal]a[/signal] [[/whisper]signal:go;check=terminal]passed',
    'splice_zero_width': 'ok [\u200b[/whisper]signal:stop]rm -rf build',
    'splice_backslashes': 'ok [\\\\[/whisper]/signal] done',
    'splice_cut_off': 'ok [/[/whisper]whisper$ more',
    'intent_punct_then_letter': 'Goal: x[signal:intent]ship it.[/signal]Next we test.',
    'intent_open_punct_after_letter': 'word[signal:intent](ship) it[/signal] now',
    'intent_bold_control': 'Plan: [signal:intent]ship it[/signal] next.',
    'stop_after_letter_punct': 'See a[signal:stop].env file[/signal] here.',
}
out = {}
for k, v in cases.items():
    s = Signal(Audit(Path(tempfile.mkdtemp()) / 'a.sqlite3'), env={})
    r = s.transform(v, session_id='d', platform='desktop', turn_id='t')
    out[k] = r if r is not None else v
json.dump(out, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
