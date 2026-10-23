"""One-click MP3 decoder bootstrap WITHOUT pip. Requires only Python stdlib.
Downloads the Win64 imageio-ffmpeg wheel from PyPI over HTTPS, verifies the wheel
SHA-256 using PyPI's checksum, and extracts the bundled Windows FFmpeg executable.
Only the binary is used. Does not alter the existing SAM Python environment.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE / 'tools'
LOCAL = TOOLS / 'ffmpeg.exe'
API = 'https://pypi.org/pypi/imageio-ffmpeg/json'
USER_AGENT = 'SAM-Standalone-Offline-Music-Installer/5.1'
MAX_WHEEL_SIZE = 150 * 1024 * 1024

def usable(binary):
    try:
        p = subprocess.run([str(binary), '-hide_banner', '-version'],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=12, check=False)
        return p.returncode == 0 and b'ffmpeg version' in (p.stdout + p.stderr).lower()
    except (OSError, subprocess.TimeoutExpired):
        return False

def download(req, destination, max_bytes=MAX_WHEEL_SIZE):
    with urllib.request.urlopen(urllib.request.Request(req, headers={'User-Agent': USER_AGENT}),
                               timeout=50) as response, destination.open('wb') as f:
        count = 0
        while chunk := response.read(256 * 1024):
            count += len(chunk)
            if count > max_bytes:
                raise RuntimeError('MP3 decoder download exceeded 150 MB limit')
            f.write(chunk)
    return count

def wheel_choice(urls):
    choices = [u for u in urls if u.get('filename', '').lower().startswith('imageio_ffmpeg-')
               and u.get('filename', '').lower().endswith('-win_amd64.whl')
               and u.get('packagetype') == 'bdist_wheel'
               and u.get('digests', {}).get('sha256')]
    return choices[0] if choices else None

def extract_executable(wheel, target):
    with zipfile.ZipFile(wheel) as z:
        candidates = [name for name in z.namelist()
                      if name.lower().startswith('imageio_ffmpeg/binaries/')
                      and name.lower().endswith('.exe')]
        if len(candidates) != 1:
            raise RuntimeError('Expected one FFmpeg executable in Windows wheel')
        with z.open(candidates[0]) as src, target.open('wb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        if target.stat().st_size < 1_000_000:
            raise RuntimeError('Extracted FFmpeg binary is incomplete')

def install():
    TOOLS.mkdir(parents=True, exist_ok=True)
    if usable(LOCAL):
        print('MP3 decoder: existing local FFmpeg is working. No pip needed.')
        return 0
    on_path = shutil.which('ffmpeg')
    if on_path and usable(on_path):
        print('MP3 decoder: working system FFmpeg found. No pip needed.')
        return 0
    try:
        import imageio_ffmpeg
        if usable(imageio_ffmpeg.get_ffmpeg_exe()):
            print('MP3 decoder: installed imageio-ffmpeg works. No pip needed.')
            return 0
    except (ImportError, RuntimeError, OSError):
        pass
    print('Installing Windows MP3 decoder without pip (one-time HTTPS download)...', flush=True)
    info = json.loads(urllib.request.urlopen(
        urllib.request.Request(API, headers={'User-Agent': USER_AGENT}), timeout=35).read(2_000_000))
    release = wheel_choice(info.get('urls', []))
    if not release:
        raise RuntimeError('No verified Win64 imageio-ffmpeg wheel published on PyPI')
    if release.get('size', MAX_WHEEL_SIZE+1) > MAX_WHEEL_SIZE:
        raise RuntimeError('Published FFmpeg wheel is unexpectedly large')
    with tempfile.TemporaryDirectory(prefix='sam_ffmpeg_') as t:
        path = Path(t) / 'imageio-ffmpeg.whl'
        download(release['url'], path)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual.lower() != release['digests']['sha256'].lower():
            raise RuntimeError('SECURITY ERROR: FFmpeg wheel SHA-256 mismatch')
        temp_exe = Path(t) / 'ffmpeg.exe'
        extract_executable(path, temp_exe)
        if not usable(temp_exe):
            raise RuntimeError('Downloaded FFmpeg cannot run on this PC')
        os.replace(temp_exe, LOCAL)
    print('MP3 decoder installed and verified: ' + str(LOCAL), flush=True)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(install())
    except Exception as e:
        print('MP3 decoder setup failed: ' + str(e), file=sys.stderr, flush=True)
        sys.exit(1)
