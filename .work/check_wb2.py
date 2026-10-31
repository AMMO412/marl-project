import json
import urllib.request

catalog = json.load(urllib.request.urlopen('http://127.0.0.1:8766/api/catalog',
                                           timeout=5))
print('version', catalog.get('version'))
print('features', catalog.get('features'))
html = urllib.request.urlopen('http://127.0.0.1:8766/', timeout=5).read().decode('utf-8')
print('planner select', 'name="planner"' in html)
print('interop option', 'interop_neutral' in html)
