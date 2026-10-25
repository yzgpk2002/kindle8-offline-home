"""Keep controller ownership while a paired headset is temporarily absent."""
import asyncio,time

class PeerUnavailable(Exception):pass

def peer_cancelled(lost):
    # Bumble cancels individual awaitables when their ACL disappears, without
    # cancelling the parent task. An explicit task.cancel() must still exit.
    task=asyncio.current_task()
    return lost and task is not None and task.cancelling()==0

async def settle_tasks(*tasks):
    """Observe failed/cancelled tasks without skipping the caller's recovery."""
    active=[task for task in tasks if task is not None]
    for task in active:
        if not task.done():task.cancel()
    return await asyncio.gather(*active,return_exceptions=True)

async def maintain(adapter,voice,commands,stop,emit,retry_delays=(2,5,10,20)):
    attempt=0
    while not stop.is_set():
        try:
            emit('connecting',session=False,recording=False,playing=False,message='')
            await adapter.open()
            attempt=0
            voice.last_packet=time.monotonic()
            voice.status()
            while not stop.is_set() and adapter.active() and time.monotonic()-voice.last_packet<=5:
                try:action=await asyncio.wait_for(commands.get(),.25)
                except asyncio.TimeoutError:
                    voice.tick();continue
                try:voice.command(action)
                except (ValueError,OSError) as error:
                    emit('session_ready',session=True,recording=voice.capture is not None,playing=voice.playing,message=str(error))
        except PeerUnavailable:
            pass
        finally:
            voice.pause_link()
            await adapter.close()
            # Commands from the old link must not start capture on reconnection.
            while not commands.empty():commands.get_nowait()
        if stop.is_set():return
        await adapter.health()
        emit('waiting_headset',session=False,recording=False,playing=False,message='')
        delay=retry_delays[min(attempt,len(retry_delays)-1)]
        attempt+=1
        try:await asyncio.wait_for(stop.wait(),delay)
        except asyncio.TimeoutError:pass
