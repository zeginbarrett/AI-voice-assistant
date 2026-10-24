"""Loopback control API embedded in the running Windows SAM voice bridge.
Existing private-LAN mic, playback and authentication paths are unchanged.
"""
from __future__ import annotations
import json, hmac, logging, os, re, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG=logging.getLogger('sam.control')
BRAIN=None
PORT=8781
PRESETS={
 'auto':(0,0,70,170,65,42),'off':(1,0,0,0,0,35),
 'solid':(2,15,120,255,75,45),'breathe':(3,38,130,255,75,45),
 'rainbow':(4,255,90,140,70,45),'disco':(5,255,20,220,70,58),
 'strobe':(6,255,255,255,65,35),'chase':(7,24,200,255,75,60),
 'pulse':(8,255,20,80,75,45),'sparkle':(9,100,170,255,75,55),
 'candle':(10,255,115,25,50,28),'ocean':(11,0,145,255,75,46),
 'party':(12,255,0,200,75,65),'meteor':(13,60,190,255,75,55)
}
LED=None


def _path():
    home=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.sam'))) / 'SAM'
    home.mkdir(parents=True,exist_ok=True)
    return home/'led-settings.json'


def led_state():
    global LED
    if LED is None:
        try: LED=json.loads(_path().read_text(encoding='utf-8'))
        except (OSError,ValueError): LED={'preset':'auto'}
    return LED


def apply_led(session=None):
    b=BRAIN
    if b is None:return False
    if session is None:
        with b.LOCK:session=b.CURRENT
    if not session or not session.connected or 'LED' not in session.firmware:return False
    state=led_state(); preset=state.get('preset','auto')
    config=PRESETS.get(preset,PRESETS['auto'])
    vals=[config[0],*(state.get('rgb',config[1:4]) if preset in ('solid','breathe','pulse','chase','strobe') else config[1:4]),state.get('brightness',config[4]),state.get('speed',config[5])]
    if len(vals)!=6 or any(not isinstance(v,int) or not 0<=v<=255 for v in vals):raise ValueError('Invalid stored light settings')
    return session.send(b'J'+bytes(vals))


def snapshot():
    b=BRAIN
    with b.LOCK:s=b.CURRENT
    connected=bool(s and s.connected)
    fw=s.firmware if connected else ''
    music=b.MUSIC; alarm=b.ALARMS
    alarms=[]
    if alarm:
        with alarm._lock:
            alarms=[{'name':x.get('name','Alarm'),'next_at':x['next_at'],'days':x.get('days',[])} for x in alarm._alarms[:40]]
    memo=b.MEMORY.status() if getattr(b,'MEMORY',None) is not None else {}
    return {'running':True,'connected':connected,'firmware':fw,'led_supported':bool(connected and 'LED' in fw),
            'state':s.state if connected else 'OFFLINE',
            'model':b.MODEL_CONFIG.get('ollama_model',''),
            'volume':music.volume if music else 0,
            'music':{'playing':music.playing,'paused':music._pause.is_set(),'current':music.current,'tracks':len(music.tracks)} if music else {},
            'voice_engine':b.MODEL_CONFIG.get('voice_engine','sapi'),
            'memory':{'turns':memo.get('turns',0),'notes':memo.get('notes',0)},
            'alarms':alarms,'ringing':bool(alarm and alarm._active), 'lights':led_state()}


def action(route,body):
    b=BRAIN; music=b.MUSIC
    if route=='led':
        preset=body.get('preset');
        if preset not in PRESETS:raise ValueError('Unsupported LED preset')
        current={'preset':preset}
        for key,maxval in [('brightness',100),('speed',100)]:
            if key in body:
                x=body[key]
                if type(x) is not int or not 0<=x<=maxval:raise ValueError('Invalid '+key)
                current[key]=x
        if 'rgb' in body:
            rgb=body['rgb']
            if not isinstance(rgb,list) or len(rgb)!=3 or any(type(v) is not int or not 0<=v<=255 for v in rgb):raise ValueError('Invalid RGB triplet')
            current['rgb']=rgb
        if not snapshot()['led_supported']:raise RuntimeError('LED controls require the new LED-capable firmware. Flash the board from Setup first.')
        global LED
        LED=current
        path=_path(); tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(LED,indent=2),encoding='utf-8');os.replace(tmp,path)
        if not apply_led():raise RuntimeError('Speaker disconnected before LED command was delivered')
        return {'message':'LED preset applied','lights':current}
    if route=='music':
        cmd=body.get('command')
        if cmd=='play':
            q=body.get('query','')
            if not isinstance(q,str) or len(q)>100:raise ValueError('Invalid music query')
            music._defer_play=False
            return {'message':music.play(q)}
        if cmd=='library':
            tracks=music.refresh();return {'tracks':[x[1] for x in tracks[:350]],'count':len(tracks)}
        if cmd in ('pause','resume','stop','next','previous'):
            return {'message':getattr(music,cmd)()}
        raise ValueError('Unknown music command')
    if route=='volume':
        level=body.get('level')
        if type(level) is not int or not 0<=level<=100:raise ValueError('Volume must be 0-100')
        return {'message':music.set_volume(level)}
    if route=='alarm':
        command=body.get('command','')
        if not isinstance(command,str) or not 1<=len(command)<=160:raise ValueError('Enter an alarm command')
        result=b.ALARMS.handle(command)
        if result is None:raise ValueError('Unknown alarm request')
        if b.CONTINUOUS_ALARM is not None and b.ALARMS._active is None:b.CONTINUOUS_ALARM.stop()
        return {'message':result}
    if route=='memory':
        query=body.get('query','')
        if not isinstance(query,str) or not 1<=len(query)<=160:raise ValueError('Enter a search term')
        return {'matches':[{'date':t[2],'text':t[3],'type':t[0]} for t in b.MEMORY.search(query,12)]}
    if route=='settings':
        patch=body
        path=b.ROOT/'settings.json'
        saved=json.loads(path.read_text(encoding='utf-8'))
        if 'voice_engine' in patch:
            voice=patch['voice_engine']
            if voice not in ('sapi','piper','chatterbox'):raise ValueError('Invalid voice selection')
            saved['voice_engine']=voice
        if 'model' in patch:
            model=patch['model']
            if not isinstance(model,str) or not re.fullmatch(r'[a-zA-Z0-9_.:\-/]{2,90}',model):raise ValueError('Invalid model ID')
            saved['ollama_model']=model
        tmp=path.with_name('.settings-panel-tmp.json')
        tmp.write_text(json.dumps(saved,indent=2),encoding='utf-8');os.replace(tmp,path)
        b.MODEL_CONFIG.update(saved)
        return {'message':'Settings saved. Voice model must be installed separately if not already available.'}
    if route=='test_voice':
        with b.LOCK:s=b.CURRENT
        if not s or not s.connected:raise RuntimeError('Speaker is offline')
        with s.frames_lock:
            if s.state not in ('IDLE','LISTEN'):raise RuntimeError('SAM is busy')
            s.state='THINK';s.question.clear()
        s.send(b'T')
        threading.Thread(target=s._speak_answer,args=('',),kwargs={'override':'Hello! This is a test of my selected voice.'},daemon=True).start()
        return {'message':'Voice test is playing'}
    raise ValueError('Unsupported control')


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def _reply(self,n,payload):
        data=json.dumps(payload).encode()
        self.send_response(n);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def guard(self):
        return self.client_address[0] in ('127.0.0.1','::1') and hmac.compare_digest(self.headers.get('X-Sam-Token',''),BRAIN.MODEL_CONFIG['token'])
    def do_GET(self):
        if not self.guard():return self._reply(403,{'error':'Unauthorized'})
        if self.path=='/status':return self._reply(200,snapshot())
        self._reply(404,{'error':'Unknown endpoint'})
    def do_POST(self):
        if not self.guard():return self._reply(403,{'error':'Unauthorized'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<2 or size>4096:raise ValueError('Invalid request size')
            body=json.loads(self.rfile.read(size));
            if not isinstance(body,dict):raise ValueError('Object expected')
            result=action(self.path.lstrip('/'),body)
            return self._reply(200,result)
        except (ValueError,TypeError) as exc:self._reply(400,{'error':str(exc)})
        except Exception as exc:
            LOG.exception('SAM control request failed')
            self._reply(503,{'error':str(exc)[:180]})


def start(brain):
    global BRAIN
    BRAIN=brain
    try:server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    except OSError as exc:LOG.warning('Control agent port %d unavailable: %s',PORT,exc);return
    threading.Thread(target=server.serve_forever,daemon=True,name='sam-control-agent').start()
    LOG.info('SAM LOCAL CONTROL: http://127.0.0.1:%d (authenticated)',PORT)

