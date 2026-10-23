"""Offline protocol/PC wake tests. Run with python -m unittest discover -s tests -v."""
from __future__ import annotations
import importlib.util
import io
import json
import socket
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
import numpy as np

MODULE = Path(__file__).resolve().parents[1] / 'windows' / 'sam_pc_wake.py'
spec = importlib.util.spec_from_file_location('sam_pc_wake', MODULE)
sam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sam)


def make_wav():
    b=io.BytesIO()
    with wave.open(b,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000)
        f.writeframes((np.ones(800,dtype='<i2')*123).tobytes())
    return b.getvalue()

class TestSound(unittest.TestCase):
    def test_raw_stereo_channels(self):
        x=np.zeros((1600,2),dtype='<i2');x[:,0]=210;x[:,1]=50
        sel,left,right=sam.choose_channel(x)
        self.assertEqual(sel,0)
        self.assertAlmostEqual(left['rms'],210/32768)
        self.assertAlmostEqual(right['rms'],50/32768)
    def test_zero_channel_selected_other(self):
        x=np.zeros((200,2),dtype='<i2');x[:,1]=140
        sel,*_=sam.choose_channel(x)
        self.assertEqual(sel,1)
    def test_wake_phrase(self):
        self.assertTrue(sam.is_wake('Hey Sam, can you help?'))
        self.assertTrue(sam.is_wake('Hi Sam'))
        self.assertFalse(sam.is_wake('They sample a record'))
        self.assertFalse(sam.is_wake('Turn on the light'))
    def test_detect_corrupt_mic_and_hallucinations(self):
        damaged=np.zeros((100,2),dtype='<i2')
        damaged[::8,:]=200
        self.assertTrue(sam.mic_corrupt(sam.measure(damaged[:,0]),sam.measure(damaged[:,1])))
        clean=np.ones((100,2),dtype='<i2')*200
        self.assertFalse(sam.mic_corrupt(sam.measure(clean[:,0]),sam.measure(clean[:,1])))
        self.assertTrue(sam.spurious_transcript('Heh, heh, heh, heh'))
        self.assertTrue(sam.spurious_transcript('Okay. Okay. Okay. Okay.'))
        self.assertFalse(sam.spurious_transcript('Sam, can you turn on the lights?'))

    def test_raw_four_slot_packet_decoding_and_phase_probe(self):
        class DummySocket:
            def sendall(self, x): pass
        with patch.object(sam.Session,'watch',return_value=None), patch.object(sam,'wav_file') as out:
            ses=sam.Session(DummySocket(),'127.0.0.1')
            ses.firmware='SAM-MIC-RAW4-v2'
            raw=np.zeros((512,4),dtype='<i2')
            raw[:,0]=100; raw[:,2]=250
            ses.ingest_raw4(raw.tobytes())
            actual=ses.snapshot()
            np.testing.assert_array_equal(actual[:,0],raw[:,2])
            np.testing.assert_array_equal(actual[:,1],raw[:,0])
            ses.slot_diagnostics()
            self.assertEqual(out.call_count,4)
            self.assertEqual(out.call_args_list[0].args[0],'last_raw_slot0.wav')
            self.assertEqual(out.call_args_list[2].args[0],'last_raw_slot2.wav')
            ses.connected=False

    def test_stereo_standard_i2s_packet_has_no_raw4_padding(self):
        class DummySocket:
            def sendall(self, x): pass
        with patch.object(sam.Session,'watch',return_value=None):
            ses=sam.Session(DummySocket(),'127.0.0.1')
            raw=np.zeros((512,2),dtype='<i2')
            raw[:,0]=np.arange(512,dtype=np.int16)*3+1
            raw[:,1]=np.arange(512,dtype=np.int16)*2+1
            ses.ingest(raw.tobytes())
            np.testing.assert_array_equal(ses.snapshot(),raw)
            l,r=sam.measure(raw[:,0]),sam.measure(raw[:,1])
            self.assertFalse(sam.mic_corrupt(l,r))
            ses.connected=False

    def test_hands_free_wake_uses_phrase(self):
        self.assertTrue(sam.is_wake('Hey Sam'))
        self.assertTrue(sam.is_wake('Hey Sam what time is it'))
        self.assertFalse(sam.is_wake('Heh heh heh'))

    def test_auth_valid(self):
        sam.MODEL_CONFIG={'token':'testing-abc'}
        a,b=socket.socketpair()
        try:
            a.sendall(b'SAMSTREAM1 testing-abc\n')
            sam.read_auth(b)
        finally:a.close();b.close()
    def test_auth_reject(self):
        sam.MODEL_CONFIG={'token':'testing-abc'}
        a,b=socket.socketpair()
        try:
            a.sendall(b'SAMSTREAM1 incorrect\n')
            with self.assertRaises(PermissionError): sam.read_auth(b)
        finally:a.close();b.close()
    def test_framed_stream_k2_and_reply(self):
        sam.MODEL_CONFIG={'token':'testing-abc','ollama_model':'mock','port':8765}
        wav=make_wav()
        with patch.object(sam,'recognize',return_value='Can you tell me a joke?'), \
             patch.object(sam,'ollama',return_value='Test reply'), \
             patch.object(sam,'tts',return_value=wav), \
             patch.object(sam.Session,'diag',return_value=None):
            server=sam.StreamServer(('127.0.0.1',0),sam.StreamHandler)
            runner=threading.Thread(target=server.serve_forever,daemon=True)
            runner.start()
            sock=socket.create_connection(server.server_address,timeout=3)
            try:
                sock.sendall(b'SAMSTREAM1 testing-abc\n')
                self.assertEqual(sam.read_exact(sock,1),b'O')
                arr=np.ones((512,2),dtype='<i2')*300
                blob=b'A'+(512).to_bytes(2,'little')+arr.tobytes()
                for _ in range(15):sock.sendall(blob)
                sock.sendall(b'B')
                self.assertEqual(sam.read_exact(sock,1),b'L')
                for _ in range(30):sock.sendall(blob)
                # Force the diagnostic test question window to close quickly.
                deadline=time.monotonic()+3
                while sam.CURRENT is None and time.monotonic()<deadline:time.sleep(.03)
                self.assertIsNotNone(sam.CURRENT)
                sam.CURRENT.listen_start=time.monotonic()-3
                sam.CURRENT.speech_started=True
                sam.CURRENT.last_voice=time.monotonic()-2
                sam.CURRENT.listen_until=time.monotonic()-.1
                self.assertEqual(sam.read_exact(sock,1),b'T')
                self.assertEqual(sam.read_exact(sock,1),b'P')
                self.assertEqual(sam.CURRENT.reply,wav)
                sock.sendall(b'D')
                self.assertEqual(sam.read_exact(sock,1),b'L')
            finally:
                sock.close();server.shutdown();server.server_close()

class TestV5Features(unittest.TestCase):
    def test_speaker_volume_intents(self):
        player=sam.sam_music.MusicPlayer('local-test')
        player.session=None
        with patch.object(player,'set_volume',side_effect=lambda v: f'Volume set to {v} percent.') as method:
            self.assertEqual(sam.sam_music.parse_command('Sam, set volume to 40 percent',player),
                             'Volume set to 40 percent.')
            method.assert_called_with(40)
        with patch.object(player,'adjust_volume',return_value='done') as method:
            self.assertEqual(sam.sam_music.parse_command('volume up',player),'done')
            method.assert_called_with(10)
            self.assertEqual(sam.sam_music.parse_command('volume down',player),'done')
            method.assert_called_with(-10)
            sam.sam_music.parse_command('turn up the volume',player)
            method.assert_called_with(10)
            sam.sam_music.parse_command('lower the volume',player)
            method.assert_called_with(-10)

    def test_music_intents_do_not_replace_normal_conversation(self):
        player=sam.sam_music.MusicPlayer('local-test')
        with patch.object(player,'play',return_value='Playing tracks') as play:
            self.assertEqual(sam.sam_music.parse_command('play some music',player),'Playing tracks')
            play.assert_called_once_with('some music')
        self.assertIsNone(sam.sam_music.parse_command('Tell me about classical music',player))

    def test_mute_unmute(self):
        player=sam.sam_music.MusicPlayer('local-test')
        player.volume=80
        with patch.object(player,'set_volume',return_value='muted') as setter:
            self.assertEqual(sam.sam_music.parse_command('mute speaker',player),'muted')
            setter.assert_called_with(0)

    def test_auto_followup_after_reply_and_timeout_to_wake(self):
        class Sock:
            def __init__(self):self.sent=[]
            def sendall(self,b):self.sent.append(b)
        sock=Sock()
        with patch.object(sam.Session,'watch',return_value=None):
            ses=sam.Session(sock,'192.168.8.178')
            ses.state='REPLY'
            ses.reply=b'RIFF'
            ses.close_reply()
            self.assertEqual(ses.state,'LISTEN')
            self.assertEqual(ses.listen_kind,'FOLLOWUP')
            self.assertIn(b'L',sock.sent)
            self.assertGreater(ses.listen_until,time.monotonic()+9)
            ses.connected=False

    def test_wake_phrase_with_question_is_preserved(self):
        self.assertTrue(sam.is_wake('Hey Sam what time is it'))
        class Sock:
            def __init__(self):self.sent=[]
            def sendall(self,b):self.sent.append(b)
        sock=Sock()
        with patch.object(sam.Session,'watch',return_value=None), \
             patch.object(sam.Session,'_speak_answer',return_value=None) as answer:
            ses=sam.Session(sock,'192.168.8.178')
            ses.awake('voice','what time is it')
            self.assertEqual(ses.state,'THINK')
            self.assertIn(b'T',sock.sent)
            # The response is started without losing the phrase after 'Hey Sam'.
            for _ in range(40):
                if answer.called:break
                time.sleep(.01)
            answer.assert_called_once_with('what time is it')
            ses.connected=False

    def test_time_uses_pc_clock_not_llm(self):
        with patch.object(sam,'ollama',side_effect=AssertionError('Ollama must not invent time')):
            reply,followup=sam.response_for('What time is it?')
        self.assertIn('It is',reply)
        self.assertTrue(followup)

    def test_hallucination_phrase_filter(self):
        self.assertTrue(sam.spurious_transcript('Okay. All right. '*10))
        self.assertTrue(sam.spurious_transcript('I am going to do a little bit of this. '*10))
        self.assertFalse(sam.spurious_transcript('Tell me a story about a dragon'))

if __name__=='__main__':unittest.main()
