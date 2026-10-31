import sys

sys.path.insert(0, r'D:\Desktop\MARL项目\planning_middle_demo')
import workbench_server as wb

opened = []
wb.webbrowser.open = lambda url: opened.append(url)
sys.argv = ['workbench_server.py', '--port', '8766', '--open',
            '--open-path', '/?new=interop']
wb.main()
print('opened', opened)
