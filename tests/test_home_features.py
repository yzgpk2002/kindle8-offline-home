import sys,tempfile,unittest,wave,math,array
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent.parent/'src'/'app'))
from home_store import HomeStore
from media_prepare import prepare
from voice_session import VoiceSession
from types import SimpleNamespace

class Features(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=HomeStore(self.root)
    def tearDown(self):self.tmp.cleanup()
    def wav(self,path,rate=8000,seconds=20):
        path.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(path),'wb') as w:w.setparams((1,2,rate,0,'NONE',''));w.writeframes(b'\x10\x00'*rate*seconds)
    def test_date_validation_and_preservation(self):
        self.store.save_memo('2024-02-29','hello');self.store.save_memo('2025-12-31','world')
        with self.assertRaises(ValueError):self.store.save_memo('2025-02-29','invalid')
        self.assertEqual(self.store.memos(),{'2024-02-29':'hello','2025-12-31':'world'})
    def test_inventory_id_cannot_traverse(self):
        self.wav(self.root/'music'/'album'/'track.wav');rows=self.store.media('music')
        self.assertEqual(len(rows),1);self.assertEqual(self.store.resolve('music',rows[0]['id']).name,'track.wav')
        for bad in ('../calendar.json','a'*24):
            with self.assertRaises(ValueError):self.store.resolve('music',bad)
    def test_music_resampled_and_long_playback_bounded(self):
        source=self.root/'music'/'track.wav';self.wav(source,16000)
        ready=prepare(source,self.root);events=[];v=VoiceSession(self.root,lambda *a,**k:events.append(a))
        v.command({'action':'play_file','file':ready.relative_to(self.root).as_posix()})
        self.assertLessEqual(len(v.downlink),16384)
        p=SimpleNamespace(data=b'\0'*60,data_total_length=60,connection_handle=1,packet_status=0)
        for _ in range(4001):v.receive(p)
        self.assertTrue(v.playing,'Music must not stop at the old 15 second limit')
        v.pause_link();self.assertFalse(v.playing);self.assertIsNone(v.reader)
    def test_external_worker_path_rejected(self):
        v=VoiceSession(self.root,lambda *a,**k:None)
        with self.assertRaises(ValueError):v.command({'action':'play_file','file':'../outside.wav'})
    def test_wrong_format_does_not_interrupt_existing_playback(self):
        good=self.root/'good.wav';bad=self.root/'bad.wav';self.wav(good);self.wav(bad,16000)
        v=VoiceSession(self.root,lambda *a,**k:None,good);v.command('play')
        with self.assertRaises(ValueError):v.command({'action':'play_file','file':'bad.wav'})
        self.assertTrue(v.playing);v.close()
if __name__=='__main__':unittest.main()
