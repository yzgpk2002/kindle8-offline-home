"""Local calendar and media inventory; never accept an arbitrary playback path."""
import datetime, hashlib, json, os, threading, wave
from pathlib import Path

class HomeStore:
    def __init__(self, data, music=None):
        self.data=Path(data); self.music=Path(music) if music else self.data/'music'
        self.lock=threading.Lock()

    def memos(self):
        try:return json.loads((self.data/'calendar.json').read_text(encoding='utf-8'))
        except FileNotFoundError:return {}

    def save_memo(self, day, text):
        if not isinstance(day,str) or datetime.date.fromisoformat(day).isoformat()!=day:raise ValueError('Invalid date')
        if not isinstance(text,str) or len(text)>2000:raise ValueError('Memo too long')
        with self.lock:
            rows=self.memos()
            if text:rows[day]=text
            else:rows.pop(day,None)
            tmp=self.data/'calendar.tmp'
            with tmp.open('w',encoding='utf-8') as f:
                json.dump(rows,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
            tmp.replace(self.data/'calendar.json')

    def media(self, kind):
        if kind not in ('recordings','music','answers'):raise ValueError('Invalid media kind')
        root=self.music if kind=='music' else self.data/kind
        if not root.exists():return []
        root=root.resolve(); rows=[]
        # Walk at most two directory levels and 1000 entries, not the entire user disk.
        seen=0
        for base,dirs,files in os.walk(root,followlinks=False):
            depth=len(Path(base).relative_to(root).parts)
            dirs[:]=sorted(d for d in dirs if not (Path(base)/d).is_symlink())[:100] if depth<1 else []
            for name in files:
                seen+=1
                if seen>1000:break
                p=Path(base)/name
                if p.is_symlink() or p.suffix.lower() not in ('.wav','.mp3'):continue
                if kind!='music' and p.suffix.lower()!='.wav':continue
                try:
                    stat=p.stat()
                    if stat.st_size>64*1024*1024:continue
                    rel=p.relative_to(root).as_posix()
                    ident=hashlib.sha256((kind+'/'+rel).encode()).hexdigest()[:24]
                    rows.append({'id':ident,'name':rel,'bytes':stat.st_size,'modified':stat.st_mtime,'kind':kind})
                except OSError:continue
            if seen>1000:break
        return sorted(rows,key=lambda r:r['modified'],reverse=True)[:200]

    def resolve(self, kind, ident):
        if not isinstance(ident,str) or len(ident)!=24:raise ValueError('Invalid media id')
        row=next((r for r in self.media(kind) if r['id']==ident),None)
        if row is None:raise ValueError('Media not found')
        root=(self.music if kind=='music' else self.data/kind).resolve()
        p=(root/row['name']).resolve()
        if root not in p.parents or not p.is_file():raise ValueError('Invalid media path')
        return p

def validate_pcm(path):
    with wave.open(str(path)) as w:
        if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,8000):
            raise ValueError('Playback requires mono PCM16 8kHz WAV')
        if w.getnframes()>8000*1800:raise ValueError('Audio exceeds 30 minutes')
