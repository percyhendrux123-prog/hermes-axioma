"""Pass-18 Desktop cases: non-ASCII digits after '$' and spans inside links.
Run: python3 pass18-cases.py out.json, then feed out.json to desktop-pipeline-probe.mts."""
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from axioma.audit import Audit
from axioma.signal import Signal

cases = {
    'arabic_digit': 'السعر $٥٠ شهريا. [signal:caution]this bills the team card[/signal] ok?',
    'devanagari_digit': 'Price $५ a month. [signal:caution]this bills the team card[/signal] ok?',
    'thai_digit': 'Price $๕ a month. [signal:caution]this bills the team card[/signal] ok?',
    'math_digit': 'Price $\U0001d7d3 a month. [signal:caution]this bills the team card[/signal] ok?',
    'ascii_digit_control': 'It costs $49 a month. [signal:caution]this bills the team card[/signal] ok?',
    'www_link': 'see www.example.com/[signal:stop]delete prod[/signal] ok?',
    'angle_link': 'see <http://x.y/[signal:stop]delete prod[/signal]> ok?',
    'double_backslash_closer': '[signal:stop]x[\\\\/signal] ok?',
}
out = {}
for k, v in cases.items():
    s = Signal(Audit(Path(tempfile.mkdtemp()) / 'a.sqlite3'), env={})
    out[k] = s.transform(v, session_id='d', platform='desktop', turn_id='t')
json.dump(out, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
