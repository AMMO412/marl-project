import io
import ast

s = io.open('behaviors.py', encoding='utf-8').read()
i = s.find('def _patrol_target')
seg = s[i:i + 3000]
print('intercept blocks:', seg.count("kind in ('intercept', 'reserve')"))
print('air blocks:', seg.count("kind == 'air'"))
ast.parse(s)
print('syntax ok')
