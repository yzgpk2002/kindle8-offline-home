"""One HCI owner across earbud case cycles; native recovery only on exit/fault."""
import asyncio,contextlib,json,os,time,xml.etree.ElementTree as ET
from pathlib import Path
from bumble import core,hci,hfp,rfcomm
from bumble.device import Device
from bumble.keys import MemoryKeyStore,PairingKeys
from bumble.transport.common import StreamPacketSource,StreamPacketSink
import audio_lifecycle
from voice_session import VoiceSession
from persistent_link import PeerUnavailable,maintain,settle_tasks,peer_cancelled
from headset_profile import ChannelCache,open_channel
DATA=Path('/mnt/us/kt3-home')

class HeadsetLink:
    def __init__(self,device,target,voice):
        self.device=device;self.target=target;self.voice=voice
        self.address=hci.Address(target,hci.Address.PUBLIC_DEVICE_ADDRESS)
        self.connection=None;self.sco=None;self.listeners=[];self.lost=asyncio.Event()
        self.ready=asyncio.Event();self.protocols=[]
        self.config=hfp.AgConfiguration(supported_ag_features=[],supported_ag_indicators=[hfp.AgIndicatorState.call(),hfp.AgIndicatorState.callsetup(),hfp.AgIndicatorState.callheld(),hfp.AgIndicatorState.service(),hfp.AgIndicatorState.signal(),hfp.AgIndicatorState.roam(),hfp.AgIndicatorState.battchg()],supported_hf_indicators=[],supported_ag_call_hold_operations=[],supported_audio_codecs=[hfp.AudioCodec.CVSD])
        self.server=rfcomm.Server(device)
        channel=self.server.listen(self.on_dlc)
        device.sdp_service_records={1:hfp.make_ag_sdp_records(1,channel,self.config)}
    def on_dlc(self,dlc):
        ag=hfp.AgProtocol(dlc,self.config);self.protocols.append(ag)
        ag.on('slc_complete',lambda:self.ready.set())
    def listen(self,obj,name,fn):
        obj.on(name,fn);self.listeners.append((obj,name,fn))
    def active(self):return not self.lost.is_set()
    async def health(self):
        await asyncio.wait_for(self.device.send_command(hci.HCI_Read_Local_Version_Information_Command(),check_result=True),5)
    async def open(self):
        self.lost.clear();self.ready.clear();self.protocols.clear()
        self.connection=self.device.find_connection_by_bd_addr(self.address,core.PhysicalTransport.BR_EDR)
        if self.connection is None:
            try:
                self.connection=await asyncio.wait_for(self.device.connect(self.target,transport=core.PhysicalTransport.BR_EDR,timeout=12),20)
            except core.ConnectionError as e:
                if e.error_code in (0x04,0x08,0x0D,0x0E,0x13,0x15,0x16,0x22):raise PeerUnavailable() from e
                if e.error_code!=0x0B:raise
                for _ in range(20):
                    await asyncio.sleep(.1)
                    self.connection=self.device.find_connection_by_bd_addr(self.address,core.PhysicalTransport.BR_EDR)
                    if self.connection is not None:break
                if self.connection is None:raise PeerUnavailable() from e
            except core.TimeoutError as e:raise PeerUnavailable() from e
            except asyncio.TimeoutError as e:
                await asyncio.wait_for(self.device.cancel_connection(self.address),5)
                raise PeerUnavailable() from e
        self.listen(self.connection,'disconnection',lambda *args:self.lost.set())
        try:
            await asyncio.wait_for(self.negotiate(),90)
        except asyncio.CancelledError as e:
            if peer_cancelled(self.lost.is_set()):
                ChannelCache(DATA/'headset-channel.json').clear(self.target)
                raise PeerUnavailable() from e
            raise
        except Exception as e:
            if self.lost.is_set():raise PeerUnavailable() from e
            raise
    async def negotiate(self):
        connection=self.connection
        await asyncio.wait_for(connection.authenticate(),15)
        await asyncio.wait_for(connection.encrypt(),10)
        mux=None
        cache=ChannelCache(DATA/'headset-channel.json')
        async def open_dlc(channel):
            nonlocal mux
            if mux is None:mux=await asyncio.wait_for(rfcomm.Client(connection).start(),10)
            return await asyncio.wait_for(mux.open_dlc(channel),10)
        async def discover():return await asyncio.wait_for(hfp.find_hf_sdp_record(connection),15)
        dlc,channel,cached=await open_channel(self.target,cache,open_dlc,discover)
        self.on_dlc(dlc)
        await asyncio.wait_for(self.ready.wait(),15)
        cache.save(self.target,channel)
        print('HELD_HFP_SLC_OK', 'CACHED_CHANNEL' if cached else 'VERIFIED_CHANNEL',channel,flush=True)
        await asyncio.sleep(3)
        result=None
        def on_sco(link):
            nonlocal result
            if link.acl_connection is not connection:return
            self.sco=link
            self.listen(link,'disconnection',lambda *args:self.lost.set())
            def receive(packet):
                payload=self.voice.receive(packet)
                self.device.host.send_sco_sdu(connection_handle=packet.connection_handle,sdu=payload)
            link.sink=receive
            if result is not None and not result.done():result.set_result(link)
        def failed(status):
            if result is not None and not result.done():result.set_exception(RuntimeError('SCO setup failed: '+str(status)))
        self.listen(self.device,'sco_connection',on_sco)
        self.listen(self.device,'sco_connection_failure',failed)
        for _ in range(3):
            result=asyncio.get_running_loop().create_future()
            await asyncio.wait_for(self.device.send_command(hci.HCI_Enhanced_Setup_Synchronous_Connection_Command(connection_handle=connection.handle,**hfp.ESCO_PARAMETERS[hfp.DefaultCodecParameters.SCO_CVSD_D1].asdict()),check_result=True),5)
            try:
                await asyncio.wait_for(result,15)
                print('HELD_SCO_READY',flush=True)
                return
            except (RuntimeError,asyncio.TimeoutError):
                if self.lost.is_set():raise PeerUnavailable()
                await asyncio.sleep(2)
        raise RuntimeError('Bounded SCO setup failed')
    async def close(self):
        if self.sco:self.sco.sink=None
        for obj,name,fn in self.listeners:obj.remove_listener(name,fn)
        self.listeners.clear()
        if self.connection and self.device.find_connection_by_bd_addr(self.address,core.PhysicalTransport.BR_EDR) is self.connection:
            try:await asyncio.wait_for(self.connection.disconnect(),5)
            except (core.ProtocolError,asyncio.TimeoutError):
                # A simultaneous peer disconnect may already have removed this ACL.
                if self.device.find_connection_by_bd_addr(self.address,core.PhysicalTransport.BR_EDR) is self.connection:raise
        self.sco=None;self.connection=None;self.protocols.clear()

async def run_session(stop,commands,emit,remote):
    target=(DATA/'target.txt').read_text().strip()
    previous=None
    try:
        previous=Path(json.loads((DATA/'latest.json').read_text())['file']).resolve()
        if previous.parent.parent!=DATA/'recordings':raise ValueError('Unexpected recording path')
    except FileNotFoundError:pass
    voice=VoiceSession(DATA,emit,previous)
    prepared=False;proc=None;pump=None;beat=None;runner=None;closer=None;adapter=None
    try:
        await remote('sh /opt/kt3-home/hfp/hfp-prepare.sh '+str(os.getpid()))
        prepared=True
        token=audio_lifecycle.load()['token']
        async def heartbeat():
            while True:
                audio_lifecycle.query_service_health(token)
                audio_lifecycle.heartbeat(token)
                await asyncio.sleep(2)
        beat=asyncio.create_task(heartbeat())
        proc=await asyncio.create_subprocess_exec('/bin/sh','/opt/kt3-home/hfp/hfp-bridge.sh',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE)
        source=StreamPacketSource();sink=StreamPacketSink(proc.stdin)
        async def read():
            while data:=await proc.stdout.read(4096):source.data_received(data)
            raise RuntimeError('HCI transport closed')
        pump=asyncio.create_task(read())
        device=Device.with_hci('KT3 handsfree',hci.Address('F0:F1:F2:F3:F4:F5'),source,sink)
        device.classic_enabled=True;device.le_enabled=False;device.keystore=MemoryKeyStore()
        for d in ET.parse('/var/local/zbluetooth/bt_devices.xml').findall('.//device'):
            if d.findtext('bd_addr','').rstrip(':')==target:
                key=bytes.fromhex(d.findtext('link_key').replace(':',''))[::-1]
                await device.keystore.update(str(hci.Address(target,hci.Address.PUBLIC_DEVICE_ADDRESS)),PairingKeys(link_key=PairingKeys.Key(key),link_key_type=int(d.findtext('key_type'))))
        await asyncio.wait_for(device.power_on(),20)
        print('HELD_CONTROLLER_READY',os.getpid(),flush=True)
        adapter=HeadsetLink(device,target,voice)
        runner=asyncio.create_task(maintain(adapter,voice,commands,stop,emit))
        closer=asyncio.create_task(stop.wait())
        done,_=await asyncio.wait([runner,closer,pump,beat],return_when=asyncio.FIRST_COMPLETED)
        for task in (pump,beat,runner):
            if task in done:await task
    finally:
        try:
            await settle_tasks(runner,closer)
            voice.close()
        finally:
            await settle_tasks(beat,pump)
            if proc and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):proc.terminate()
            if prepared:
                emit('restoring',session=False,recording=False,playing=False)
                await remote('sh /opt/kt3-home/hfp/hfp-restore.sh',80)
                if not audio_lifecycle.load().get('ok'):raise RuntimeError('Native audio recovery failed')
