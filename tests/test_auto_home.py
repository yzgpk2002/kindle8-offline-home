"""Exercise fixed HTTP actions and automatic connection scheduling without hardware."""
import importlib.util,tempfile,sys,unittest,types
from pathlib import Path
from unittest.mock import patch,Mock
P=Path(__file__).parent.parent/'src'
sys.path.insert(0,str(P/'app'))
class StopLoop(Exception):pass
class AutoHome(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'data').mkdir();(self.root/'lab').mkdir()
        def mapped(value):
            s=str(value)
            if s.startswith('/mnt/us/kt3-home'):return self.root/'data'/s[len('/mnt/us/kt3-home'):].lstrip('/')
            if s.startswith('/var/local/kt3-hfp-lab'):return self.root/'lab'/s[len('/var/local/kt3-hfp-lab'):].lstrip('/')
            return Path(value)
        spec=importlib.util.spec_from_file_location('auto_home_test_target',P/'app/server.py')
        self.m=importlib.util.module_from_spec(spec)
        with patch('pathlib.Path',side_effect=mapped):spec.loader.exec_module(self.m)
        self.m.Path=mapped
    def tearDown(self):self.tmp.cleanup()
    def post(self,path):
        f=types.SimpleNamespace(path=path,headers={'X-KT3-Token':self.m.TOKEN},valid=lambda:True,reply=lambda c,s:(c,s.copy()))
        return self.m.Handler.do_POST(f)
    def test_resume_queues_without_duplicate_worker(self):
        self.m.state.update(auto_connect=False,busy=True)
        code,_=self.post('/api/audio/session')
        self.assertEqual(code,202);self.assertTrue(self.m.AUTO_WAKE.is_set());self.assertTrue(self.m.state['auto_connect'])
    def test_pause_connecting_without_worker(self):
        self.m.state.update(state='connecting',session=False)
        code,_=self.post('/api/session/close')
        self.assertEqual(code,202);self.assertFalse(self.m.state['auto_connect'])
    def test_pause_existing_session_sends_close(self):
        w=Mock();w.poll.return_value=None;self.m.worker=w
        self.post('/api/session/close');w.stdin.write.assert_called_once_with('close\n')
    def test_library_does_not_close_duplex(self):
        self.m.state.update(busy=True,session=True)
        w=Mock();self.m.worker=w
        with patch.object(self.m.threading,'Thread') as t:
            code,_=self.post('/api/menu/library');self.assertEqual(code,202);t.return_value.start.assert_called_once()
        self.assertTrue(self.m.state['session']);w.stdin.write.assert_not_called()
    def test_exit_disables_reconnect(self):
        with patch.object(self.m.threading,'Thread'):self.post('/api/menu/rollback')
        self.assertFalse(self.m.state['auto_connect']);self.assertTrue(self.m.state['exit_pending'])
    def test_failed_recovery_blocks_auto_resume(self):
        self.m.state['audio_disabled']=True
        code,_=self.post('/api/audio/session');self.assertEqual(code,503)
    def test_auto_loop_never_runs_two_workers(self):
        self.m.state['busy']=True
        with patch.object(self.m.AUTO_WAKE,'wait',side_effect=[False,StopLoop]),patch.object(self.m,'record') as r:
            with self.assertRaises(StopLoop):self.m.auto_connect_loop()
            r.assert_not_called()
    def test_absent_headset_retries_with_backoff(self):
        waits=[]
        def wait(delay):
            waits.append(delay)
            if len(waits)>2:raise StopLoop()
        def record(**kw):self.m.state['busy']=False
        with patch.object(self.m.AUTO_WAKE,'wait',side_effect=wait),patch.object(self.m,'record',side_effect=record) as r:
            with self.assertRaises(StopLoop):self.m.auto_connect_loop()
        self.assertEqual(r.call_count,2);self.assertEqual(waits,[2,15,30])
    def test_kual_exit_marker_closes_live_session(self):
        self.m.state.update(busy=True,session=True)
        marker=self.root/'data'/'exit-request';marker.touch()
        with patch.object(self.m.time,'sleep'),patch.object(self.m,'exit_home') as leave:self.m.exit_request_loop()
        leave.assert_called_once();self.assertFalse(marker.exists());self.assertFalse(self.m.state['auto_connect'])
if __name__=='__main__':unittest.main()
