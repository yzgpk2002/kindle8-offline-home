"""KT3 duplex worker with a bounded handshake and an independent liveness watchdog."""
import asyncio,sys,logging,xml.etree.ElementTree as ET,json,wave,array,os,signal
from pathlib import Path
from datetime import datetime
from bumble import core,hci,hfp,rfcomm
from bumble.device import Device
from bumble.keys import MemoryKeyStore,PairingKeys
from bumble.transport.common import StreamPacketSource,StreamPacketSink
from sco_capture import ScoCapture
from voice_session import VoiceSession
import audio_lifecycle
BASE=Path(__file__).resolve().parent
DATA=Path('/mnt/us/kt3-home')
TARGET=(DATA/'target.txt').read_text().strip()
STOP=asyncio.Event()
SESSION='--session' in sys.argv
COMMANDS=asyncio.Queue(maxsize=8)
def event(state,**kwargs):
    print('WEB_EVENT '+json.dumps(dict(state=state,**kwargs)),flush=True)

async def control():
    while True:
        line=await asyncio.to_thread(sys.stdin.readline)
        if not line or line.strip()=='close' or (not SESSION and line.strip()=='stop'):
            STOP.set();return
        if SESSION and line.strip() in ('record','stop','play','stop_play'):
            await COMMANDS.put(line.strip())
        elif SESSION and len(line)<1024 and line.startswith('{'):
            try:
                value=json.loads(line)
                if value.get('action')=='play_file':await COMMANDS.put(value)
            except (ValueError,AttributeError):pass

async def remote(command,timeout=40):
    p=await asyncio.create_subprocess_exec('/bin/sh','-c',command,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,start_new_session=True)
    try:
        data,_=await asyncio.wait_for(p.communicate(),timeout)
        if p.returncode:raise RuntimeError('Remote operation failed')
        return data.decode()
    except BaseException:
        if p.returncode is None:
            os.killpg(p.pid,signal.SIGKILL)
            await p.wait()
        raise

async def run():
    proc=None;capture=None;pump=None;prepared=False;voice=None
    downlink=b'';sent=0
    if SESSION:
        previous=None
        try:
            previous=Path(json.loads((DATA/'latest.json').read_text())['file']).resolve()
            if previous.parent.parent!=DATA/'recordings':raise ValueError('Unexpected recording path')
        except FileNotFoundError:pass
        voice=VoiceSession(DATA,event,previous)
    if '--duplex-test' in sys.argv:
        previous=Path(json.loads((DATA/'latest.json').read_text())['file'])
        with wave.open(str(previous)) as wav:
            if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,8000):raise ValueError('Duplex requires mono PCM16 8kHz')
            samples=array.array('h',wav.readframes(120000))
        downlink=array.array('h',(int(x*.5) for x in samples)).tobytes()
    try:
        await remote('sh /opt/kt3-home/hfp/hfp-prepare.sh '+str(os.getpid()))
        prepared=True
        event('connecting')
        proc=await asyncio.create_subprocess_exec('/bin/sh','/opt/kt3-home/hfp/hfp-bridge.sh',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE)
        source=StreamPacketSource();sink=StreamPacketSink(proc.stdin)
        async def read():
            while data:=await proc.stdout.read(4096):source.data_received(data)
        pump=asyncio.create_task(read())
        device=Device.with_hci('KT3 HFP laboratory',hci.Address('F0:F1:F2:F3:F4:F5'),source,sink)
        device.classic_enabled=True
        device.le_enabled=False
        device.keystore=MemoryKeyStore()
        for d in ET.parse(Path('/var/local/zbluetooth/bt_devices.xml')).findall('.//device'):
            if d.findtext('bd_addr','').rstrip(':')==TARGET:
                key=bytes.fromhex(d.findtext('link_key').replace(':',''))[::-1]
                await device.keystore.update(str(hci.Address(TARGET,hci.Address.PUBLIC_DEVICE_ADDRESS)),PairingKeys(link_key=PairingKeys.Key(key),link_key_type=int(d.findtext('key_type'))))
        print('STAGE power_on',flush=True)
        await asyncio.wait_for(device.power_on(),20)
        print('CONTROLLER',device.public_address,flush=True)
        config=hfp.AgConfiguration(supported_ag_features=[],supported_ag_indicators=[hfp.AgIndicatorState.call(),hfp.AgIndicatorState.callsetup(),hfp.AgIndicatorState.callheld(),hfp.AgIndicatorState.service(),hfp.AgIndicatorState.signal(),hfp.AgIndicatorState.roam(),hfp.AgIndicatorState.battchg()],supported_hf_indicators=[],supported_ag_call_hold_operations=[],supported_audio_codecs=[hfp.AudioCodec.CVSD])
        ready=asyncio.Event();protocols=[]
        def on_dlc(dlc):
            ag=hfp.AgProtocol(dlc,config);protocols.append(ag)
            ag.on('slc_complete',lambda:ready.set())
        channel=rfcomm.Server(device).listen(on_dlc)
        device.sdp_service_records={1:hfp.make_ag_sdp_records(1,channel,config)}
        print('STAGE connect',flush=True)
        address=hci.Address(TARGET,hci.Address.PUBLIC_DEVICE_ADDRESS)
        connection=device.find_connection_by_bd_addr(address,core.PhysicalTransport.BR_EDR)
        if connection is None:
            try:
                connection=await asyncio.wait_for(device.connect(TARGET,transport=core.PhysicalTransport.BR_EDR),20)
            except core.ConnectionError as error:
                if error.error_code!=0x0B:raise
                for _ in range(50):
                    await asyncio.sleep(.1)
                    connection=device.find_connection_by_bd_addr(address,core.PhysicalTransport.BR_EDR)
                    if connection is not None:break
                if connection is None:raise
        # Establish the existing bond before opening the SDP/RFCOMM channels.
        await asyncio.wait_for(connection.authenticate(),15)
        await asyncio.wait_for(connection.encrypt(),10)
        record=await asyncio.wait_for(hfp.find_hf_sdp_record(connection),15)
        if not record:raise RuntimeError('No HFP Handsfree SDP record')
        print('HF SDP',record,flush=True)
        print('KEY_LOOKUP',str(connection.peer_address),bool(await device.keystore.get(str(connection.peer_address))),flush=True)
        mux=await asyncio.wait_for(rfcomm.Client(connection).start(),10)
        on_dlc(await asyncio.wait_for(mux.open_dlc(record[0]),10))
        await asyncio.wait_for(ready.wait(),15)
        print('STAGE HFP_SLC_OK',flush=True)
        await asyncio.sleep(3)
        sco_ready=asyncio.get_running_loop().create_future()
        def on_sco(link):
            nonlocal capture
            if not SESSION:capture=ScoCapture(DATA/'recordings'/('capture-'+datetime.now().strftime('%Y%m%d-%H%M%S')))
            def receive(packet):
                nonlocal sent
                if voice:
                    payload=voice.receive(packet)
                    device.host.send_sco_sdu(connection_handle=packet.connection_handle,sdu=payload)
                    return
                capture(packet)
                size=packet.data_total_length
                payload=downlink[sent:sent+size].ljust(size,b'\0')
                sent+=size
                device.host.send_sco_sdu(connection_handle=packet.connection_handle,sdu=payload)
            link.sink=receive
            if not sco_ready.done():sco_ready.set_result(link)
        device.on('sco_connection',on_sco)
        def sco_failed(status):
            print('SCO_FAILURE',status,flush=True)
            if not sco_ready.done():sco_ready.set_exception(RuntimeError(f'SCO failure {status}'))
        device.on('sco_connection_failure',sco_failed)
        for preset in [hfp.DefaultCodecParameters.SCO_CVSD_D1]*3:
            sco_ready=asyncio.get_running_loop().create_future()
            print('SCO_PRESET',preset,flush=True)
            response=await device.send_command(hci.HCI_Enhanced_Setup_Synchronous_Connection_Command(connection_handle=connection.handle,**hfp.ESCO_PARAMETERS[preset].asdict()),check_result=True)
            print('SCO_COMMAND_RESPONSE',response,flush=True)
            try:
                await asyncio.wait_for(sco_ready,15)
                break
            except (RuntimeError,asyncio.TimeoutError) as error:
                print('SCO_ATTEMPT_FAILED',repr(error),flush=True)
                await asyncio.sleep(2)
        else:raise RuntimeError('All bounded SCO presets failed')
        if voice:
            voice.last_packet=asyncio.get_running_loop().time()
            token=audio_lifecycle.load()['token']
            voice.status()
            next_beat=0
            while not STOP.is_set():
                now=asyncio.get_running_loop().time()
                if now-voice.last_packet>5:
                    event('disconnected',message='Headset audio link closed; waiting to reconnect')
                    break
                if now>=next_beat:
                    audio_lifecycle.heartbeat(token);next_beat=now+2
                try:action=await asyncio.wait_for(COMMANDS.get(),.25)
                except asyncio.TimeoutError:
                    voice.tick();continue
                voice.command(action)
            print('SESSION_SUMMARY rx_bytes',voice.rx,'tx_audio_bytes',voice.tx,flush=True)
            return
        event('recording',limit=15)
        try:await asyncio.wait_for(STOP.wait(),15)
        except asyncio.TimeoutError:pass
        print('CAPTURE packets',capture.packets,'bytes',capture.bytes,flush=True)
        print('DUPLEX downlink_pcm_bytes',min(sent,len(downlink)),flush=True)
        if not capture.bytes:raise RuntimeError('No microphone samples received')
    finally:
        if voice:voice.close()
        if capture:capture.close()
        if proc and proc.returncode is None:proc.terminate()
        if pump:pump.cancel()
        if prepared:
            event('restoring')
            await remote('sh /opt/kt3-home/hfp/hfp-restore.sh',80)
            restored=audio_lifecycle.load()
            if not restored.get('ok'):raise RuntimeError('Native audio recovery failed')
        if capture and capture.bytes:
            output=capture.directory/'microphone-8k.wav'
            with wave.open(str(output),'wb') as wav:
                wav.setparams((1,2,8000,0,'NONE','not compressed'))
                wav.writeframes((capture.directory/'sco.raw').read_bytes())
            event('saved',file=str(output),seconds=capture.bytes/16000)

async def main():
    listener=asyncio.create_task(control())
    try:
        if SESSION:
            from persistent_headset import run_session
            await run_session(STOP,COMMANDS,event,remote)
        else:await asyncio.wait_for(run(),120)
        event('complete')
    except Exception as error:
        event('error',message=str(error));raise
    finally:
        listener.cancel()

logging.basicConfig(level=logging.WARNING)
if __name__=='__main__':asyncio.run(main())
