import json
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, r'D:\Desktop\MARL项目\planning_middle_demo')
import workbench_server as wb


class OldHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"service": "planning-middle-workbench/v1",
                           "runs": [], "scenarios": {}}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


old = HTTPServer(('127.0.0.1', 8767), OldHandler)
threading.Thread(target=old.serve_forever, daemon=True).start()

opened = []
wb.webbrowser.open = lambda url: opened.append(url)
sys.argv = ['workbench_server.py', '--port', '8767', '--open']
threading.Thread(target=wb.main, daemon=True).start()
time.sleep(3)
print('opened', opened)
try:
    catalog = json.load(urllib.request.urlopen('http://127.0.0.1:8768/api/catalog',
                                               timeout=5))
    print('fallback server version', catalog.get('version'))
    print('features', catalog.get('features'))
finally:
    old.shutdown()
