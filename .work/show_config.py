import io
t = io.open('workbench/index.html', encoding='utf-8').read()
i = t.find('config-form')
print(t[i:i + 3800])
