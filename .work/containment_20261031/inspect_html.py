import io

s = io.open('index.html', encoding='utf-8').read()
i = s.find('<section id="page-overview"')
j = s.find('<section id="page-tasks"')
k = s.find('<section id="page-containment"')
print('overview start:', repr(s[i:i + 110]))
print('overview tail :', repr(s[j - 240:j]))
print('containment   :', repr(s[k:k + 130]))
print('containment end:', repr(s[k:k + 200][-80:]))
print('after containment:', repr(s[s.find('</section>', k):s.find('</section>', k) + 40]))
