import sys,tempfile,unittest,wave,time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).parent.parent/'src'/'app'))
from voice_session import VoiceSession

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name);self.events=[]
        self.voice=VoiceSession(self.data,lambda name,**kw:self.events.append((name,kw)))
    def tearDown(self):self.voice.close();self.temp.cleanup()
    def packet(self,data=b'\x10\x00'*30):return SimpleNamespace(data=data,data_total_length=len(data),connection_handle=1,packet_status=0)
    def capture(self):
        self.voice.command('record')
        for _ in range(4):self.voice.receive(self.packet())
        self.voice.command('stop')
        return self.voice.latest
    def test_idle_does_not_store_microphone(self):
        self.assertEqual(self.voice.receive(self.packet()),bytes(60));self.assertFalse((self.data/'recordings').exists())
    def test_record_stop_play_uses_same_session(self):
        p=self.capture();self.assertFalse(self.voice.closed)
        with wave.open(str(p)) as w:self.assertEqual(w.getnframes(),120)
        self.voice.command('play');self.assertEqual(self.voice.receive(self.packet()),b'\x08\x00'*30)
        for _ in range(3):self.voice.receive(self.packet())
        self.assertFalse(self.voice.playing);self.assertEqual(self.voice.receive(self.packet()),bytes(60))
    def test_capture_and_play_overlap(self):
        old=self.capture();self.voice.command('play');self.voice.command('record')
        self.assertNotEqual(self.voice.receive(self.packet()),bytes(60))
        self.voice.command('stop');self.assertNotEqual(old,self.voice.latest)
        self.assertTrue(old.exists());self.assertTrue(self.voice.playing)
    def test_empty_recording_preserves_latest(self):
        p=self.capture();self.voice.command('record');self.voice.command('stop');self.assertEqual(p,self.voice.latest)
    def test_recording_timeout_without_packets(self):
        self.voice.command('record');self.voice.receive(self.packet());self.voice.started=time.monotonic()-16;self.voice.tick()
        self.assertIsNone(self.voice.capture);self.assertTrue(self.voice.latest.exists())
    def test_bounded_capture(self):
        self.voice.command('record')
        for _ in range(4001):self.voice.receive(self.packet())
        self.assertIsNone(self.voice.capture)
        with wave.open(str(self.voice.latest)) as w:self.assertEqual(w.getnframes(),120000)
    def test_invalid_command_and_packet(self):
        with self.assertRaises(ValueError):self.voice.command('reboot')
        p=self.packet();p.data_total_length+=1
        with self.assertRaises(ValueError):self.voice.receive(p)
    def test_close_saves_and_does_not_reopen(self):
        self.voice.command('record');self.voice.receive(self.packet());self.voice.close()
        self.assertTrue(self.voice.latest.exists())
        with self.assertRaises(ValueError):self.voice.command('record')
    def test_disconnect_saves_partial_capture_without_resuming_play(self):
        self.capture();self.voice.command('play');self.voice.command('record')
        self.voice.receive(self.packet());self.voice.pause_link()
        self.assertTrue(self.voice.latest.exists());self.assertIsNone(self.voice.capture)
        self.assertFalse(self.voice.playing);self.assertFalse(self.voice.closed)
        self.assertEqual(self.voice.receive(self.packet()),bytes(60))
        self.voice.command('play');self.assertTrue(self.voice.playing)
if __name__=='__main__':unittest.main()
