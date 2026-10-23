"""Test the repaired pip-free FFmpeg installer without any Internet access."""
import io, json, tempfile, hashlib, zipfile, unittest, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
import install_ffmpeg as x

class TestNoPipMusicInstall(unittest.TestCase):
    def test_pick_win64_wheel(self):
        links=[{'filename':'imageio_ffmpeg-0.6.0-py3-none-any.whl','packagetype':'bdist_wheel','digests':{'sha256':'abc'}},
               {'filename':'imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl','packagetype':'bdist_wheel','digests':{'sha256':'def'}}]
        self.assertEqual(x.wheel_choice(links),links[1])
    def test_extract_ffmpeg_binary(self):
        with tempfile.TemporaryDirectory() as td:
            wheel=Path(td)/'a.whl';target=Path(td)/'ffmpeg.exe'
            with zipfile.ZipFile(wheel,'w') as z:
                z.writestr('imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.exe',b'MZ'+b'X'*1_500_000)
            x.extract_executable(wheel,target)
            self.assertEqual(target.stat().st_size,1_500_002)
            self.assertTrue(target.read_bytes().startswith(b'MZ'))
    def test_complete_install_wheel_sha256_verified_and_no_pip(self):
        wheel=io.BytesIO()
        with zipfile.ZipFile(wheel,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.exe',b'MZ'+b'X'*1_500_000)
        wheel_bytes=wheel.getvalue()
        digest=hashlib.sha256(wheel_bytes).hexdigest()
        metadata={'urls':[{'filename':'imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl','packagetype':'bdist_wheel',
                           'digests':{'sha256':digest},'size':len(wheel_bytes),'url':'https://files.pythonhosted.org/test.whl'}]}
        def mock_open(req,timeout=None):
            url=req.full_url if hasattr(req,'full_url') else req
            return io.BytesIO(json.dumps(metadata).encode() if 'pypi.org' in url else wheel_bytes)
        with tempfile.TemporaryDirectory() as td,patch.object(x,'TOOLS',Path(td)), patch.object(x,'LOCAL',Path(td)/'ffmpeg.exe'),\
             patch.object(x,'usable',side_effect=lambda p: Path(p).is_file()),\
             patch('install_ffmpeg.shutil.which',return_value=None),\
             patch.dict(sys.modules, {'imageio_ffmpeg': None}),\
             patch('install_ffmpeg.urllib.request.urlopen',side_effect=mock_open):
            # fake exe smoke test; actual binary cannot be executed on Linux.
            self.assertEqual(x.install(),0)
            self.assertTrue((Path(td)/'ffmpeg.exe').is_file())
            self.assertEqual(x.install(),0) # idempotent; no download necessary

if __name__=='__main__':unittest.main()
