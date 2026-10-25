"""Bounded WAV conversion for held SCO playback. MP3 uses our optional static decoder."""
import audioop,hashlib,subprocess,wave,os,shutil
from pathlib import Path

def prepare(source,data):
    source=Path(source);data=Path(data);cache=data/'media-cache';cache.mkdir(exist_ok=True)
    if source.stat().st_size>64*1024*1024:raise ValueError('Music file exceeds 64 MB')
    if shutil.disk_usage(data).free<400*1024*1024:raise ValueError('Music conversion needs 400 MB free space')
    key=hashlib.sha256((str(source)+str(source.stat().st_mtime_ns)).encode()).hexdigest()[:20]
    dest=cache/(key+'.wav')
    if dest.exists():return dest
    tmp=cache/(key+'.tmp');intermediate=None
    try:
        if source.suffix.lower()=='.mp3':
            decoder=Path('/opt/kt3-home/app/mp3decode')
            if not decoder.exists():raise ValueError('MP3 decoder is not installed; use WAV')
            intermediate=cache/(key+'.pcm.wav')
            subprocess.run([str(decoder),str(source),str(intermediate)],check=True,timeout=45,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            source=intermediate
        with wave.open(str(source)) as src,wave.open(str(tmp),'wb') as dst:
            rate=src.getframerate();width=src.getsampwidth();channels=src.getnchannels()
            if width not in (1,2,3,4) or channels not in (1,2) or not 8000<=rate<=96000:raise ValueError('Unsupported WAV format')
            if src.getnframes()>rate*1800:raise ValueError('Music exceeds 30 minutes')
            dst.setparams((1,2,8000,0,'NONE','not compressed'));state=None
            while raw:=src.readframes(8192):
                if width==1:raw=audioop.bias(raw,1,-128)
                if width!=2:raw=audioop.lin2lin(raw,width,2)
                if channels==2:raw=audioop.tomono(raw,2,.5,.5)
                raw,state=audioop.ratecv(raw,2,1,rate,8000,state);dst.writeframesraw(raw)
        tmp.replace(dest)
        # Only generated cache files are evicted, never original recordings/music.
        for old in cache.glob('*.wav'):
            if old!=dest:
                try:old.unlink()
                except OSError:pass
        return dest
    finally:
        if tmp.exists():tmp.unlink()
        if intermediate and intermediate.exists():intermediate.unlink()
