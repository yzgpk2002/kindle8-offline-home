import importlib.util,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
p=Path(__file__).parent.parent/'src'/'app'/'audio_lifecycle.py'
spec=importlib.util.spec_from_file_location('lifecycle',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Recovery(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.d=Path(self.t.name);m.D=self.d;m.HEARTBEAT_DIR=self.d;m.BOOT=self.d/'boot';m.BOOT.write_text('boot-A')
        self.s={'boot':'boot-A','token':'session-A','finished':False}
        (self.d/'session.json').write_text(json.dumps(self.s))
    def tearDown(self):self.t.cleanup()
    def test_old_session_no_effect(self):
        with patch.object(m,'run',side_effect=AssertionError('must not touch device')):m.restore('session-B')
        self.assertFalse((self.d/'restore-lock').exists())
    def test_old_boot_no_effect(self):
        m.BOOT.write_text('boot-B')
        with patch.object(m,'run',side_effect=AssertionError('must not touch device')):m.restore('session-A')
    def test_finished_no_effect(self):
        self.s['finished']=True;m.save(self.s)
        with patch.object(m,'run',side_effect=AssertionError('must not touch device')):m.restore('session-A')
    def test_reused_pid_not_signalled(self):
        with patch.object(m,'identity',return_value={'pid':3,'start':'new','comm':'btd'}),patch.object(m.os,'kill') as kill:
            m.signal_saved({'pid':3,'start':'old','comm':'btd'},m.signal.SIGTERM);kill.assert_not_called()
    def test_native_waits_for_ready(self):
        with patch.object(m,'run',return_value='stop/waiting') as run,patch.object(m,'waitprop',return_value=True) as wait:
            m.native_ready();self.assertEqual(run.call_args_list[1].args,('initctl','start','audiomgrd'));self.assertEqual(wait.call_args.args[-1],16)
    def test_native_failure_not_retried(self):
        with patch.object(m,'run',return_value='start/running') as run,patch.object(m,'waitprop',return_value=False):
            with self.assertRaises(RuntimeError):m.native_ready()
            self.assertEqual(run.call_count,1)
    def test_previous_boot_lock_archived(self):
        (self.d/'session-lock').mkdir();(self.d/'restore-lock').mkdir();m.BOOT.write_text('boot-B')
        with patch.object(m.os,'kill',side_effect=AssertionError('No old PID signals allowed')):m.startup()
        self.assertFalse((self.d/'session-lock').exists());self.assertTrue((self.d/'recovery-failed').exists())
        self.assertTrue((self.d/'interrupted-session-A.json').exists())
    def test_current_boot_lock_preserved(self):
        (self.d/'session-lock').mkdir()
        with self.assertRaises(RuntimeError):m.startup()
        self.assertTrue((self.d/'session-lock').exists())
    def test_healthy_hour_long_session_kept(self):
        m.heartbeat_path('session-A').write_text('3599')
        self.assertFalse(m.lease_expired(self.s,0,3600))
    def test_stalled_heartbeat_expires(self):
        m.heartbeat_path('session-A').write_text('100')
        self.assertTrue(m.lease_expired(self.s,0,113))
    def test_handshake_still_bounded(self):
        self.assertFalse(m.lease_expired(self.s,10,129))
        self.assertTrue(m.lease_expired(self.s,10,131))
    def test_wrong_session_heartbeat_ignored(self):
        m.heartbeat_path('session-B').write_text('999')
        self.assertTrue(m.lease_expired(self.s,0,1000))
    def test_heartbeat_renewal(self):
        with patch.object(m.time,'monotonic',return_value=800):m.heartbeat('session-A')
        self.assertFalse(m.lease_expired(self.s,0,803))
    def test_new_session_does_not_restore_unowned_power_flag(self):
        with patch.object(m,'setprop') as setter:
            m.restore_power({'power':'0','power_overridden':False})
            setter.assert_not_called()
    def test_legacy_session_restores_owned_power_flag(self):
        with patch.object(m,'setprop') as setter:
            m.restore_power({'power':'0'})
            setter.assert_called_once_with('com.lab126.powerd','preventScreenSaver','0')
    def test_prepare_keeps_physical_power_key_available(self):
        def prop(service,name):return '0' if name=='preventScreenSaver' else '1'
        with patch.object(m,'prop',side_effect=prop),patch.object(m,'run',return_value='11'),patch.object(m,'identity',side_effect=lambda pid:{'pid':int(pid),'start':'123','comm':'test'}),patch.object(m,'setprop') as setter,patch.object(m.subprocess,'Popen') as popen:
            popen.return_value.pid=99
            m.prepare(12)
            setter.assert_not_called()
            self.assertFalse(m.load()['power_overridden'])
            self.assertTrue((self.d/'session-lock').is_dir())
    def test_teardown_waits_for_stable_off_not_first_sample(self):
        clock=[0.0]
        def sleep(dt):clock[0]+=dt
        def run(*args,**kwargs):
            return 'start/running' if 1<=clock[0]<1.5 else 'stop/waiting'
        with patch.object(m.time,'monotonic',side_effect=lambda:clock[0]),patch.object(m.time,'sleep',side_effect=sleep),patch.object(m,'prop',return_value='0'),patch.object(m,'run',side_effect=run):
            m.wait_native_stopped()
        self.assertGreaterEqual(clock[0],3.5)
    def test_teardown_never_ready_is_bounded(self):
        clock=[0.0]
        with patch.object(m.time,'monotonic',side_effect=lambda:clock[0]),patch.object(m.time,'sleep',side_effect=lambda dt:clock.__setitem__(0,clock[0]+dt)),patch.object(m,'prop',return_value='2'),patch.object(m,'run') as run:
            with self.assertRaises(RuntimeError):m.wait_native_stopped(seconds=3)
            run.assert_not_called()
        self.assertEqual(clock[0],3)
    def test_query_proxy_failure_is_detected(self):
        self.s['query_proxy']={'pid':3,'start':'old','comm':'lua'};m.save(self.s)
        with patch.object(m,'same',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'query service exited'):m.query_service_health('session-A')
    def test_query_handoff_refuses_upstart_owned_daemon(self):
        self.s['worker']={'pid':3};self.s['processes']={'btfd':{'pid':4}};m.save(self.s)
        with patch.object(m,'same',return_value=True),patch.object(m,'run',return_value='start/running'),patch.object(m,'signal_saved') as signaler:
            with self.assertRaisesRegex(RuntimeError,'managed by Upstart'):m.handoff_queries()
            signaler.assert_not_called()
    def test_legacy_recovery_does_not_restart_query_publisher(self):
        with patch.object(m,'run') as run:m.restore_queries(self.s);run.assert_not_called()
    def test_query_recovery_restarts_native_only_after_proxy_stops(self):
        s={'query_mode':'lua-v1','query_proxy':{'pid':3,'start':'old','comm':'lua'}}
        calls=[]
        clock=[0.0]
        def run(*args,**kwargs):
            if args[0]=='initctl':return 'stop/waiting'
            calls.append('start-native')
        with patch.object(m.time,'monotonic',side_effect=lambda:clock[0]),patch.object(m.time,'sleep',side_effect=lambda dt:clock.__setitem__(0,clock[0]+dt)),patch.object(m,'signal_saved',side_effect=lambda *a:calls.append('stop-proxy')),patch.object(m,'same',return_value=False),patch.object(m,'run',side_effect=run),patch.object(m,'prop',return_value='0'):
            m.restore_queries(s)
        self.assertEqual(calls,['stop-proxy','start-native'])
        self.assertGreaterEqual(clock[0],2)
if __name__=='__main__':unittest.main()
