import json
import urllib.request

catalog = json.load(urllib.request.urlopen('http://127.0.0.1:8766/api/catalog',
                                           timeout=5))
print('version', catalog['version'])
print('default', catalog['default_run'])
for run in catalog['runs'][:3]:
    print(run['id'], run.get('planner'), run.get('scenario'))
html = urllib.request.urlopen('http://127.0.0.1:8766/?new=interop',
                              timeout=5).read().decode('utf-8')
print('motion select', 'name="motion"' in html)
print('planner select', 'name="planner"' in html)
print('asl option', '<option value="asl_city"' in html)
print('interop option', '<option value="interop_neutral"' in html)
