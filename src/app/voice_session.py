"""Bounded, command-driven PCM duplex session; no Bluetooth connection management."""
import array,time,wave,uuid
from pathlib import Path
from sco_capture import ScoCapture

class VoiceSession:
    def __init__(self,data,emit,latest=None):
        self.data=Path(data);self.emit=emit;self.latest=latest
        self.capture=None;self.started=0;self.downlink=b'';self.offset=0
        self.playing=False;self.closed=False;self.rx=0;self.tx=0
        self.last_packet=time.monotonic()
        self.reader=None;self.remaining=0

    def status(self):
        self.emit('session_ready',session=True,recording=self.capture is not None,playing=self.playing)

    def command(self,action):
        if self.closed:raise ValueError('Session closed')
        if isinstance(action,dict):
            if action.get('action')!='play_file':raise ValueError('Invalid media action')
            path=(self.data/action.get('file','')).resolve()
            if self.data.resolve() not in path.parents or path.suffix.lower()!='.wav':raise ValueError('Invalid playback path')
            self.open_audio(path);self.status();return
        if action=='record':
            if self.capture:return
            directory=self.data/'recordings'/('session-'+uuid.uuid4().hex[:12])
            self.capture=ScoCapture(directory,max_bytes=240000)
            self.started=time.monotonic()
        elif action=='stop':self.save()
        elif action=='play':
            if self.latest is None:raise ValueError('No saved recording')
            self.open_audio(self.latest)
        elif action=='stop_play':self.stop_audio()
        else:raise ValueError('Unknown session action')
        self.status()

    def stop_audio(self):
        if self.reader:self.reader.close()
        self.reader=None;self.remaining=0;self.playing=False;self.downlink=b'';self.offset=0

    def open_audio(self,path):
        from home_store import validate_pcm
        validate_pcm(path)
        self.stop_audio();self.reader=wave.open(str(path))
        self.remaining=self.reader.getnframes()*2;self.playing=self.remaining>0
        self.refill()

    def refill(self):
        if not self.reader:return
        samples=array.array('h',self.reader.readframes(8192))
        self.downlink=array.array('h',(int(x*.5) for x in samples)).tobytes();self.offset=0
        if not self.downlink:self.stop_audio()

    def receive(self,packet):
        size=packet.data_total_length
        if len(packet.data)!=size:raise ValueError('SCO size mismatch')
        self.rx+=size
        self.last_packet=time.monotonic()
        if self.capture:
            self.capture(packet)
            if self.capture.closed or time.monotonic()-self.started>=15:self.save()
        payload=b''
        while self.playing and len(payload)<size:
            chunk=self.downlink[self.offset:self.offset+size-len(payload)]
            payload+=chunk;self.offset+=len(chunk);self.remaining-=len(chunk)
            if self.remaining<=0:self.stop_audio();self.status();break
            if self.offset>=len(self.downlink):self.refill()
        self.tx+=len(payload)
        return payload.ljust(size,b'\0')

    def save(self):
        capture=self.capture
        if capture is None:return
        self.capture=None;capture.close()
        if capture.bytes:
            path=capture.directory/'microphone-8k.wav'
            raw=(capture.directory/'sco.raw').read_bytes()
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,8000,0,'NONE','not compressed'));wav.writeframes(raw)
            self.latest=path
            self.emit('saved',file=str(path),seconds=capture.bytes/16000,session=True)
        self.status()

    def tick(self):
        if self.capture and time.monotonic()-self.started>=15:self.save()

    def close(self):
        self.save();self.closed=True;self.stop_audio()

    def pause_link(self):
        """Preserve the latest recording, but never resume capture or playback implicitly."""
        self.save();self.stop_audio()
