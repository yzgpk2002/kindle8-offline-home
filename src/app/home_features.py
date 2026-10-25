"""Calendar/media/AI tasks, separate from the Bluetooth ownership state machine."""
import json,threading,time,urllib.request,urllib.parse,wave
from pathlib import Path
from home_store import HomeStore,validate_pcm
from media_prepare import prepare

class HomeFeatures:
    def __init__(self,data,play):
        self.data=Path(data);self.store=HomeStore(data);self.play=play
        self.lock=threading.Lock();self.busy=False
        self.media_state={'state':'idle','error':''}
        self.ai={'state':'unconfigured','text':'','answer':'','error':''}
        self.cancel=threading.Event()

    def config(self):
        p=self.data/'speech-config.json'
        if not p.exists():raise ValueError('Configure the companion speech service first')
        c=json.loads(p.read_text());u=urllib.parse.urlsplit(c['url'])
        if u.scheme not in ('http','https') or u.username or u.password or u.query or u.fragment:raise ValueError('Invalid service URL')
        return c

    def remote(self,path,body=None,raw=False):
        c=self.config();data=body if isinstance(body,bytes) else json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(c['url'].rstrip('/')+path,data=data,headers={'Authorization':'Bearer '+c['token'],'Content-Type':'audio/wav' if isinstance(body,bytes) else 'application/json'})
        # Do not forward the service token across an HTTP redirect.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        with urllib.request.build_opener(NoRedirect).open(req,timeout=8) as r:
            out=r.read(3*1024*1024+1)
            if len(out)>3*1024*1024:raise ValueError('Service response too large')
        return out if raw else json.loads(out)

    def get(self,route,q):
        if route=='/api/memos':return {'memos':self.store.memos()}
        if route=='/api/media':return {'items':self.store.media(q.get('kind',['recordings'])[0]),'folder':str(self.store.music)}
        if route=='/api/media/status':return self.media_state.copy()
        if route=='/api/ai/status':
            result=self.ai.copy();result['configured']=(self.data/'speech-config.json').exists();return result
        return None

    def start(self,fn):
        with self.lock:
            if self.busy:raise ValueError('Another media or voice task is running')
            self.busy=True;self.cancel.clear()
        def run():
            try:fn()
            finally:
                with self.lock:self.busy=False
        threading.Thread(target=run,daemon=True).start()

    def post(self,route,body,latest):
        if route=='/api/memos':self.store.save_memo(body['date'],body['text']);return {'ok':True}
        if route=='/api/media/play':
            source=self.store.resolve(body['kind'],body['id'])
            def play():
                self.media_state={'state':'preparing','error':''}
                try:
                    ready=prepare(source,self.data)
                    if not self.cancel.is_set():self.play(ready);self.media_state={'state':'playing','error':''}
                except Exception as e:self.media_state={'state':'error','error':str(e)[:120]}
            self.start(play);return {'ok':True}
        if route=='/api/media/cancel':self.cancel.set();return {'ok':True}
        if route in ('/api/ai/transcribe','/api/ai/chat'):
            self.config()
            if route.endswith('transcribe') and not latest:raise ValueError('Record and save a question first')
            text=body.get('text','')
            if route.endswith('chat') and (not isinstance(text,str) or not 1<=len(text.strip())<=2000):raise ValueError('Enter a question first')
            def work():
                try:
                    self.ai.update(state='working',error='')
                    raw=Path(latest).read_bytes() if route.endswith('transcribe') else {'text':text}
                    ident=self.remote('/v1/transcribe' if route.endswith('transcribe') else '/v1/chat',raw)['id']
                    end=time.monotonic()+190
                    while time.monotonic()<end and not self.cancel.wait(1):
                        status=self.remote('/v1/status')
                        if status.get('id')!=ident:raise ValueError('Voice job was replaced')
                        self.ai.update({k:status.get(k,'') for k in ('state','text','answer','error')})
                        if status['state'] in ('transcribed','error'):return
                        if status['state']=='done':
                            folder=self.data/'answers';folder.mkdir(exist_ok=True)
                            output=folder/'reply.wav';tmp=folder/'reply.tmp'
                            tmp.write_bytes(self.remote('/v1/audio/'+ident,raw=True));validate_pcm(tmp);tmp.replace(output)
                            # Never queue a reply across a headset disconnect or an explicit exit.
                            if not self.cancel.is_set():self.play(output)
                            return
                    raise ValueError('AI request cancelled or timed out')
                except Exception as e:self.ai.update(state='error',error=str(e)[:140])
            self.start(work);return {'ok':True}
        if route=='/api/ai/cancel':self.cancel.set();self.ai['state']='cancelled';return {'ok':True}
        return None
