import json
import urllib.request

catalog = json.load(urllib.request.urlopen('http://127.0.0.1:8766/api/catalog',
                                           timeout=5))
default = next(r for r in catalog['runs'] if r['id'] == catalog['default_run'])
assert catalog['version'] == '2026-10-30-interop-map-fix', catalog['version']
assert default['planner'] == 'interop', default
html = urllib.request.urlopen('http://127.0.0.1:8766/?new=interop',
                              timeout=5).read().decode('utf-8')
assert 'name="motion"' not in html
assert 'name="planner"' not in html
assert html.count('<option value="interop_neutral"') == 1
assert html.count('<option value="asl_city"') == 1
js = urllib.request.urlopen('http://127.0.0.1:8766/app.js', timeout=5).read().decode('utf-8')
assert "get('new')==='interop'" in js
assert 'config-planner' not in js and 'config-motion' not in js
print('OK', catalog['version'], default['id'], default['planner'])
