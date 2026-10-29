"""Generate a fresh run and open its standalone replay."""
import json
from datetime import datetime
import webbrowser
from demo import ROOT, read_scene, simulate, export

if __name__ == '__main__':
    config = json.loads((ROOT / 'scenario.json').read_text(encoding='utf-8-sig'))
    payload = simulate(read_scene(), config)
    out = ROOT / 'outputs' / datetime.now().strftime('run_%Y%m%d_%H%M%S_%f')
    export(payload, out)
    webbrowser.open((out / 'index.html').as_uri())
