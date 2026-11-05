"""All Desktop pipeline cases, reproducibly: the hand-written set in desktop-pipeline-cases.py plus
every reply-shaped string literal (one holding a [signal or [whisper tag) in tests/test_signal.py,
each rendered for platform=desktop. Replaces the hand-assembled 60-case JSON, which was built by
appending scratch generators and could not be regenerated (its pass-11/12 inputs were not kept).
Run: python3 desktop-pipeline-all.py out.json, then feed out.json to desktop-pipeline-probe.mts."""
import ast, json, re, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from axioma.audit import Audit
from axioma.signal import Signal

base = Path(tempfile.mkdtemp()) / 'base.json'
subprocess.run([sys.executable, str(Path(__file__).with_name('desktop-pipeline-cases.py')), str(base)], check=True)
out = json.loads(base.read_text())
tree = ast.parse((ROOT / 'tests' / 'test_signal.py').read_text())
seen = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r'(?i)\[\s*/?\s*(signal|whisper)', node.value):
        text = node.value
        if text in seen or len(text) > 2000:
            continue
        seen.add(text)
        s = Signal(Audit(Path(tempfile.mkdtemp()) / 'a.sqlite3'), env={})
        r = s.transform(text, session_id='d', platform='desktop', turn_id='t')
        out['test_L%d_%d' % (node.lineno, len(seen))] = r if r is not None else text
json.dump(out, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
print(len(out))
