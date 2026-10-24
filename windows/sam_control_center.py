"""SAM Control Center - Windows desktop app backed by Edge/Chrome app mode.
Python stdlib server on 127.0.0.1:8780. The existing Windows SAM brain runs
its separate authenticated control agent on 127.0.0.1:8781.
"""
from __future__ import annotations
import hmac,json,os,secrets,socket,subprocess,sys,threading,urllib.error,urllib.request,webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
WIN=ROOT/'windows'
UI=WIN/'sam_panel_ui'
PORT=8780
SESSION_KEY=secrets.token_urlsafe(24)
MIME={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.png':'image/png','.jpg':'image/jpeg','.ico':'image/x-icon'}


def settings():
    path=WIN/'settings.json'
    if not path.exists():return {}
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def agent(method,path,body=None):
    token=settings().get('token','')
    if not token:raise RuntimeError('SAM is not installed yet. Use the Setup tab.')
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request('http://127.0.0.1:8781'+path,data=data,method=method,
        headers={'X-Sam-Token':token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=4) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        try: detail=json.load(exc).get('error','Control unavailable')
        except Exception:detail=str(exc)
        raise RuntimeError(detail)
    except (OSError,ValueError) as exc:
        raise RuntimeError('SAM is not currently running. Click Start SAM in Setup.') from exc


def launch_script(name):
    path=ROOT/name
    if not path.is_file():raise ValueError('Missing '+name+' from installation')
    if os.name!='nt':raise RuntimeError('Setup and flashing require Windows.')
    subprocess.Popen(['cmd.exe','/c','start','"SAM Setup"','cmd.exe','/k',str(path)],cwd=str(ROOT),creationflags=0)
    return {'message':name+' launched in a separate Windows console. Follow its prompts.'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):pass
    def write(self,status,obj,ctype='application/json; charset=utf-8'):
        data=json.dumps(obj).encode('utf-8') if isinstance(obj,(dict,list)) else obj
        self.send_response(status)
        self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'")
        self.end_headers()
        try:self.wfile.write(data)
        except (ConnectionError,BrokenPipeError):pass
    def authorized(self):
        return self.client_address[0] in ('127.0.0.1','::1') and hmac.compare_digest(self.headers.get('X-Sam-Session',''),SESSION_KEY)
    def do_GET(self):
        p=urlsplit(self.path).path
        if p=='/api/session':return self.write(200,{'session':SESSION_KEY,'installed':(WIN/'settings.json').exists(),'root':str(ROOT)})
        if p=='/api/status':
            if not self.authorized():return self.write(403,{'error':'Unauthorized'})
            try:return self.write(200,agent('GET','/status'))
            except RuntimeError as exc:return self.write(200,{'running':False,'error':str(exc),'installed':(WIN/'settings.json').exists()})
        if p=='/':p='/index.html'
        if p not in ('/index.html','/app.js','/style.css','/sam_hardware.png'):
            return self.write(404,b'Not found','text/plain')
        src=UI/p.lstrip('/')
        if not src.is_file():return self.write(404,b'UI file missing','text/plain')
        return self.write(200,src.read_bytes(),MIME.get(src.suffix,'application/octet-stream'))
    def do_POST(self):
        if not self.authorized():return self.write(403,{'error':'Unauthorized'})
        origin=self.headers.get('Origin')
        if origin and origin!='http://127.0.0.1:8780':return self.write(403,{'error':'Invalid origin'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.write(415,{'error':'Expected JSON'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 2<=n<=4096:raise ValueError('Invalid request size')
            payload=json.loads(self.rfile.read(n))
            if not isinstance(payload,dict):raise ValueError('Expected object')
            p=urlsplit(self.path).path
            if p=='/api/install':
                command=payload.get('command')
                scripts={'install':'RUN_SAM_TEST.bat','flash':'RUN_SAM_TEST.bat','start':'START_SAM.bat','voice':'CHOOSE_SAM_VOICE.bat','decoder':'INSTALL_MUSIC_DECODER.bat'}
                if command not in scripts:raise ValueError('Unsupported action')
                result=launch_script(scripts[command])
            elif p in ('/api/led','/api/music','/api/volume','/api/alarm','/api/memory','/api/settings','/api/test_voice'):
                result=agent('POST',p.replace('/api/','/'),payload)
            else:return self.write(404,{'error':'Unknown endpoint'})
            return self.write(200,result)
        except (ValueError,TypeError) as exc:self.write(400,{'error':str(exc)})
        except RuntimeError as exc:self.write(503,{'error':str(exc)})


def open_desktop():
    url='http://127.0.0.1:8780'
    if os.name=='nt':
        for candidate in (
            Path(os.environ.get('PROGRAMFILES(X86)',''))/'Microsoft/Edge/Application/msedge.exe',
            Path(os.environ.get('PROGRAMFILES',''))/'Microsoft/Edge/Application/msedge.exe',
            Path(os.environ.get('PROGRAMFILES',''))/'Google/Chrome/Application/chrome.exe',
            Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe'):
            if candidate.is_file():
                subprocess.Popen([str(candidate),'--app='+url,'--window-size=1320,920'])
                return
    webbrowser.open(url)


def main():
    if not UI.joinpath('index.html').is_file():raise RuntimeError('Dashboard files not installed')
    try:server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    except OSError as exc:
        print('SAM Control Center already running? Open http://127.0.0.1:8780 in your browser.');return
    print('SAM Control Center: http://127.0.0.1:8780 (local PC only)')
    threading.Timer(.5,open_desktop).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()

