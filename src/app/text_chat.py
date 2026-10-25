"""Text-only DeepSeek client. Credentials stay outside the USB-visible volume."""
import json, os, threading, urllib.request, urllib.error
from pathlib import Path

CONFIG = Path('/var/local/kt3-home/deepseek.json')
URL = 'https://api.deepseek.com/chat/completions'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class TextChat:
    def __init__(self, config=CONFIG):
        self.path=Path(config); self.lock=threading.Lock(); self.busy=False
        self.generation=0; self.messages=[]; self.state='idle'; self.error=''

    def config(self):
        try:
            st=self.path.stat()
            if os.name!='nt' and st.st_mode & 0o077:raise ValueError('API config permissions must be 600')
            c=json.loads(self.path.read_text(encoding='utf-8'))
            key=c.get('api_key','').strip()
            if not key or key=='YOUR_API_KEY':raise ValueError('API Key not configured')
            if not key.isascii() or any(ch.isspace() for ch in key):raise ValueError('Invalid API Key')
            model=c.get('model','deepseek-flash')
            if model not in ('deepseek-flash','deepseek-v4-pro'):raise ValueError('Unsupported model')
            return key,model
        except (OSError,json.JSONDecodeError,AttributeError):raise ValueError('API Key not configured')

    def status(self):
        try:self.config(); configured=True
        except ValueError:configured=False
        with self.lock:
            return dict(configured=configured,busy=self.busy,state=self.state if configured else 'unconfigured',error=self.error,messages=list(self.messages))

    def clear(self):
        with self.lock:
            self.generation+=1; self.messages=[]; self.state='idle'; self.error=''
        # An in-flight request is not retried. Keep busy until its bounded I/O ends.
        return {'ok':True}

    def send(self,text):
        if not isinstance(text,str) or not 1<=len(text.strip())<=2000:raise ValueError('Enter 1-2000 characters')
        key,model=self.config()
        with self.lock:
            if self.busy:raise ValueError('A request is still running; please wait')
            self.busy=True; self.state='working'; self.error=''; generation=self.generation
            # Bound context and retain complete user/assistant pairs only.
            history=[]; size=0
            for i in range(len(self.messages)-2,-1,-2):
                pair=self.messages[i:i+2]; n=sum(len(m['content']) for m in pair)
                if size+n>10000 or len(history)>=6:break
                history=pair+history; size+=n
            question={'role':'user','content':text.strip()}
        def run():
            answer=None; error=''
            try:
                data=json.dumps({'model':model,'messages':history+[question],'stream':False,'max_tokens':1024,'thinking':{'type':'disabled'}}).encode()
                req=urllib.request.Request(URL,data=data,headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
                with urllib.request.build_opener(NoRedirect).open(req,timeout=45) as r:
                    raw=r.read(262145)
                if len(raw)>262144:raise ValueError('Response too large')
                answer=json.loads(raw)['choices'][0]['message']['content']
                if not isinstance(answer,str) or not answer.strip() or len(answer)>16000:raise ValueError('Invalid answer')
            except urllib.error.HTTPError as e:
                error={401:'API Key invalid',402:'API balance insufficient',429:'Rate limited; try later'}.get(e.code,'API request failed (HTTP %s)'%e.code)
            except Exception:error='Network timeout or invalid response; no automatic retry'
            finally:
                with self.lock:
                    self.busy=False
                    if generation==self.generation:
                        self.error=error; self.state='error' if error else 'done'
                        if not error:self.messages=(history+[question,{'role':'assistant','content':answer}])[-8:]
        threading.Thread(target=run,daemon=True).start()
        return {'ok':True}
