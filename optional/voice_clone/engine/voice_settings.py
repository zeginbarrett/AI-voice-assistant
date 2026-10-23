"""Activate or restore custom voice without overwriting any other SAM settings."""
import json
from pathlib import Path
import sys

def save_atomic(p:Path,obj):
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2),encoding='utf-8');tmp.replace(p)

def activate(win,python):
    p=win/'settings.json'
    data=json.loads(p.read_text(encoding='utf-8'))
    original=win/'voice_before_clone.json'
    if not original.is_file():
        save_atomic(original,{k:data.get(k) for k in ('voice_engine','piper_voice','sapi_voice')})
    data['voice_engine']='chatterbox'
    data['clone_python']=str(python.resolve())
    save_atomic(p,data)
    print('SAM will use cloned voice. Old voice choices saved in:',original)

def restore(win):
    p=win/'settings.json';backup=win/'voice_before_clone.json'
    data=json.loads(p.read_text(encoding='utf-8'))
    if not backup.is_file():
        data['voice_engine']='sapi'
    else:
        old=json.loads(backup.read_text(encoding='utf-8'))
        for key,val in old.items():
            if val is not None:data[key]=val
            else:data.pop(key,None)
    data.pop('clone_python',None)
    save_atomic(p,data)
    print('Previous SAM voice restored; no firmware changed.')

if __name__=='__main__':
    op=sys.argv[1];win=Path(sys.argv[2]);
    if op=='activate':activate(win,Path(sys.argv[3]))
    elif op=='restore':restore(win)
    else:raise SystemExit('Expected activate or restore')
