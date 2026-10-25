import asyncio,sys,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent.parent/'src'/'app'))
from persistent_link import maintain,PeerUnavailable,settle_tasks,peer_cancelled

class FakeVoice:
    def __init__(self):self.last_packet=time.monotonic();self.pauses=0;self.actions=[];self.ready=0
    def pause_link(self):self.pauses+=1
    def status(self):self.ready+=1
    def command(self,action):self.actions.append(action)
    def tick(self):pass

class PersistentTests(unittest.IsolatedAsyncioTestCase):
    async def test_absent_peer_keeps_owner_and_reconnects_without_stale_record(self):
        stop=asyncio.Event();commands=asyncio.Queue();voice=FakeVoice();events=[]
        class Adapter:
            opens=0;closes=0;checks=0
            async def open(self):
                self.opens+=1
                if self.opens==1:
                    commands.put_nowait('record');raise PeerUnavailable()
                stop.set()
            def active(self):return True
            async def close(self):self.closes+=1
            async def health(self):self.checks+=1
        adapter=Adapter()
        await maintain(adapter,voice,commands,stop,lambda state,**kw:events.append(state),(.001,))
        self.assertEqual(adapter.opens,2);self.assertEqual(adapter.checks,1)
        self.assertEqual(voice.ready,1);self.assertEqual(voice.actions,[])
        self.assertEqual(events,['connecting','waiting_headset','connecting'])
    async def test_exit_interrupts_long_absent_retry_wait(self):
        stop=asyncio.Event();waiting=asyncio.Event();voice=FakeVoice()
        class Adapter:
            async def open(self):raise PeerUnavailable()
            async def close(self):pass
            async def health(self):pass
        def emit(state,**kw):
            if state=='waiting_headset':waiting.set()
        task=asyncio.create_task(maintain(Adapter(),voice,asyncio.Queue(),stop,emit,(60,)))
        await asyncio.wait_for(waiting.wait(),1);stop.set()
        await asyncio.wait_for(task,1)
    async def test_controller_failure_propagates_for_recovery(self):
        class Adapter:
            async def open(self):raise PeerUnavailable()
            async def close(self):pass
            async def health(self):raise RuntimeError('transport lost')
        with self.assertRaisesRegex(RuntimeError,'transport lost'):
            await maintain(Adapter(),FakeVoice(),asyncio.Queue(),asyncio.Event(),lambda *a,**kw:None,(.001,))
    async def test_failed_child_does_not_skip_recovery_cleanup(self):
        async def fail():raise RuntimeError('transport lost')
        failed=asyncio.create_task(fail());pending=asyncio.create_task(asyncio.sleep(60))
        await asyncio.sleep(0)
        results=await settle_tasks(failed,pending,None)
        self.assertIsInstance(results[0],RuntimeError);self.assertTrue(pending.cancelled())
    async def test_peer_cancelled_future_is_retriable(self):
        f=asyncio.get_running_loop().create_future();f.cancel()
        try:await f
        except asyncio.CancelledError:self.assertTrue(peer_cancelled(True))
    async def test_explicit_task_cancel_is_never_treated_as_absent_peer(self):
        async def worker():
            try:await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.assertFalse(peer_cancelled(True));raise
        task=asyncio.create_task(worker());await asyncio.sleep(0);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task

if __name__=='__main__':unittest.main()
