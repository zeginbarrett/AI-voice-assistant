"""For optional Piper neural voice installation only. MP3s need no pip."""
import subprocess, sys, tempfile, urllib.request
from pathlib import Path

def run(*args):
    return subprocess.run([sys.executable,*args],check=False).returncode == 0

def main():
    if run('-m','pip','--version'):
        return 0
    print('This old SAM Python lacks pip. Attempting built-in ensurepip...',flush=True)
    run('-m','ensurepip','--upgrade')
    if run('-m','pip','--version'):
        return 0
    print('Fetching official PyPA pip bootstrap for neural voices...',flush=True)
    req=urllib.request.Request('https://bootstrap.pypa.io/get-pip.py',
                               headers={'User-Agent':'SAM-Voice-Setup/5.1'})
    with tempfile.TemporaryDirectory(prefix='sam_pip_') as t:
        path=Path(t)/'get-pip.py'
        with urllib.request.urlopen(req,timeout=45) as r:
            data=r.read(3_000_000)
        if not data.startswith(b'#!/usr/bin/env python') and b'pip' not in data[:2048]:
            raise RuntimeError('Unexpected bootstrap payload')
        path.write_bytes(data)
        if not run(str(path),'--disable-pip-version-check'):
            raise RuntimeError('Pip bootstrap failed')
    if not run('-m','pip','--version'):
        raise RuntimeError('pip still unavailable after bootstrap')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print('Optional neural voice dependency setup failed:',exc,file=sys.stderr)
        sys.exit(1)
