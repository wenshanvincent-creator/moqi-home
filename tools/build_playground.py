"""Build a self-contained review page with real-core code and honest fallback traces.

Live mode downloads the pinned Pyodide runtime/tzdata from its CDN, then runs
Python+SQLite in a worker on the visitor's machine. No household server exists.
Recorded mode contains only generated synthetic engine outputs, labeled as such.
"""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from moqi.playground import Sandbox

ROOT = Path(__file__).resolve().parents[1]
CORE = ['__init__.py', 'api.py', 'core.py', 'contexts.py', 'memory.py', 'memory_store.py',
        'statistics.py', 'understanding.py', 'attribution.py', 'decision.py', 'voice.py', 'playground.py']


def build(output):
    template = (ROOT/'playground/index.template.html').read_text(encoding='utf-8')
    sources = {'moqi/'+name: (ROOT/'moqi'/name).read_text(encoding='utf-8') for name in CORE}
    frames = []
    with tempfile.TemporaryDirectory() as temporary:
        sandbox = Sandbox(str(Path(temporary)/'demo.sqlite3'))
        try:
            def capture(title):
                frames.append({'title': title, 'view': sandbox.view()})
            capture('A blank home')
            for _ in range(3): sandbox.observe_day()
            capture('Three observations: not enough yet')
            sandbox.observe_day(); capture('Four observations: a habit emerges')
            for _ in range(3): sandbox.observe_day()
            capture('Seven days: evidence grows')
            sandbox.observe_day('unknown'); capture('An unknown cause is not human evidence')
            sandbox.observe_day('skip'); capture('A covered missed opportunity')
            sandbox.undo(); capture('A simulated undo: β + 3 and a lease')
            sandbox.correct('不要自动开餐厅灯'); capture('An explicit prohibition')
            sandbox.restore(); capture('Restore understanding, keep observations')
            sandbox.quiet_days(); capture('Context absent: evidence preserved, habits dormant')
        finally:
            sandbox.close()
    data = {'schema_version': 1, 'pyodide_version': '314.0.7', 'files': sources,
            'sha256': {name: hashlib.sha256(body.encode('utf-8')).hexdigest() for name,body in sources.items()},
            'recorded': frames}
    # Embedded data never becomes HTML/script text; close-tag injection is escaped.
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace('__MOQI_BUNDLE__', payload), encoding='utf-8', newline='\n')
    print(f'Built {target}; {len(CORE)} core files; {len(frames)} recorded real-engine steps')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='dist/playground/index.html')
    args = parser.parse_args()
    build(args.output)
