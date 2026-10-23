"""Safely add Chatterbox engine to a known-working SAM v5 PC bridge."""
from pathlib import Path
import sys

INJECTION='''

def synthesize_clone(message, config):
    """Use isolated, persistent Windows-only Chatterbox engine, preserving SAM mic and speaker."""
    import json as _json
    import subprocess as _subprocess
    import time as _time
    import urllib.request as _urllib
    from pathlib import Path as _Path
    global _sam_clone_proc
    exe=_Path(str(config.get('clone_python','')))
    server=HERE/'clone_server.py'
    if not exe.is_file() or not server.is_file():
        raise RuntimeError('Voice clone is not installed; rerun INSTALL_SAM_CLONED_VOICE.bat')
    url='http://127.0.0.1:18769'
    def ready():
        try:
            with _urllib.urlopen(url+'/health',timeout=1.5) as response:
                status=_json.loads(response.read())
                return status.get('service')=='sam-clone' and bool(status.get('ready'))
        except Exception:
            return False
    if not ready():
        creationflags=getattr(_subprocess,'CREATE_NO_WINDOW',0)
        if _sam_clone_proc is None or _sam_clone_proc.poll() is not None:
            log=HERE/'clone_server.log'
            with log.open('ab') as out:
                _sam_clone_proc=_subprocess.Popen(
                    [str(exe),str(server)],cwd=str(HERE),
                    stdout=out,stderr=_subprocess.STDOUT,creationflags=creationflags)
        deadline=_time.monotonic()+180
        while _time.monotonic()<deadline and not ready():
            if _sam_clone_proc is not None and _sam_clone_proc.poll() is not None:
                raise RuntimeError('Clone engine exited; see windows/clone_server.log')
            _time.sleep(1.5)
        if not ready():
            raise RuntimeError('Clone engine startup timed out; see windows/clone_server.log')
    request=_urllib.Request(url+'/speak',data=_json.dumps({'text':message}).encode('utf-8'),
                             headers={'Content-Type':'application/json'},method='POST')
    with _urllib.urlopen(request,timeout=180) as response:
        return response.read()

_sam_clone_proc=None
'''


def patch(path:Path):
    if not path.is_file():raise FileNotFoundError(path)
    src=path.read_text(encoding='utf-8')
    if 'def synthesize_clone(' in src:
        print('SAM voice code already patched; no duplicate changes')
        return
    if "if voice_type=='piper':" not in src or '\ndef speak(message,config):' not in src:
        raise ValueError('Expected SAM v5 voice code not found: refusing unsafe modification')
    backup=path.with_suffix('.before-clone.py')
    if not backup.is_file():backup.write_text(src,encoding='utf-8')
    src=src.replace('\ndef speak(message,config):',INJECTION+'\ndef speak(message,config):',1)
    src=src.replace("    if voice_type=='piper':", """    if voice_type in ('chatterbox', 'sam_clone'):
        try:data=synthesize_clone(message,config)
        except Exception as exc:
            LOG.warning('SAM clone unavailable (%s); falling back to the previous voice.',exc)
            try:
                prev=json.loads((HERE/'voice_before_clone.json').read_text(encoding='utf-8'))
                if prev.get('voice_engine')=='piper':
                    data=synthesize_piper(message,{**config,**prev})
                else:
                    data=synthesize_sapi(message,{**config,**prev})
            except Exception:
                data=synthesize_sapi(message,config)
    elif voice_type=='piper':""",1)
    compile(src,str(path),'exec')
    path.write_text(src,encoding='utf-8')
    print('SAM voice engine patched; original backed up:',backup)

if __name__=='__main__':patch(Path(sys.argv[1]).resolve())
