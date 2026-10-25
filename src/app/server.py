"""Loopback-only KT3 home. Fixed actions, no shell commands from HTTP."""
import json,os,secrets,subprocess,threading,time,wave,shutil,xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import audio_lifecycle
from home_features import HomeFeatures
from text_chat import TextChat
BASE=Path(__file__).resolve().parent
DATA=Path('/mnt/us/kt3-home')
token_file=Path('/var/local/kt3-hfp-lab/web-token')
try:TOKEN=token_file.read_text().strip()
except FileNotFoundError:
    TOKEN=secrets.token_hex(24)
    token_file.write_text(TOKEN);token_file.chmod(0o600)
LOCK=threading.Lock()
state={'state':'waiting','busy':False,'available':False,'seconds':0,'error':'','session':False,'recording':False,'playing':False,'auto_connect':True}
AUTO_WAKE=threading.Event()
if (BASE/'audio-disabled').exists() or Path('/var/local/kt3-hfp-lab/recovery-failed').exists():
    state.update(audio_disabled=True,error='Audio is paused pending recovery verification.')
worker=None
latest=None
def play_file(path):
    relative=Path(path).resolve().relative_to(DATA.resolve()).as_posix()
    with LOCK:
        if state.get('exit_pending') or not state['session'] or not worker or worker.poll() is not None:raise ValueError('Headset not ready; select play again after reconnect')
        worker.stdin.write(json.dumps({'action':'play_file','file':relative})+'\n');worker.stdin.flush()
features=HomeFeatures(DATA,play_file)
text_chat=TextChat()
try:
    latest=Path(json.loads((DATA/'latest.json').read_text())['file'])
    state['available']=latest.is_file()
    if state['available']:
        with wave.open(str(latest)) as wav:state['seconds']=wav.getnframes()/wav.getframerate()
except (OSError,ValueError,KeyError):pass
def cmd(*args,timeout=12):
    return subprocess.check_output(args,stdin=subprocess.DEVNULL,stderr=subprocess.STDOUT,timeout=timeout).decode(errors='replace').strip()
def setprop(service,prop,value):return cmd('lipc-set-prop',service,prop,str(value))
def getprop(service,prop):return cmd('lipc-get-prop',service,prop)
def audio_ready():
    cmd('sh','/opt/kt3-home/audio/start-experiment.sh',timeout=15)
    audio_lifecycle.native_ready()
    try:enabled=getprop('com.lab126.btmd','Enable')=='2'
    except subprocess.CalledProcessError:enabled=False
    if not enabled:setprop('com.lab126.btfd','BTenable','1:2')
    if not audio_lifecycle.waitprop('com.lab126.btmd','Enable',2,12):raise RuntimeError('Bluetooth is not ready')
    time.sleep(1)
def connect():
    target=(DATA/'target.txt').read_text().strip()
    devices=ET.parse('/var/local/zbluetooth/bt_devices.xml').findall('.//device')
    expected=next((d.findtext('device_name') for d in devices if d.findtext('bd_addr','').rstrip(':')==target),None)
    try:connected_name=getprop('com.lab126.btfd','BTconnectedDevName')
    except subprocess.CalledProcessError:connected_name=None
    try:
        if expected and getprop('com.lab126.audiomgrd','audioOutputConnected')=='1' and connected_name==expected:return
    except subprocess.CalledProcessError:pass
    audio_ready()
    if not audio_lifecycle.waitprop('com.lab126.btfd','BTstate',1,5):
        raise RuntimeError('Bluetooth is changing state; retry later')
    setprop('com.lab126.btfd','Connect',target)
    for _ in range(12):
        if getprop('com.lab126.audiomgrd','audioOutputConnected')=='1':
            time.sleep(2)
            return
        with LOCK:
            if not state.get('auto_connect') or state.get('exit_pending'):raise RuntimeError('Connection cancelled')
        time.sleep(1)
    raise RuntimeError('Headphones not connected; open case and retry')
def record(duplex=False,session=False):
    global worker,latest
    log=(DATA/'logs'/('record-'+str(int(time.time()))+'.log')).open('w')
    try:
        if shutil.disk_usage(DATA).free<16*1024*1024:raise RuntimeError('Recording storage is full')
        connect()
        if session:
            with LOCK:
                if not state.get('auto_connect') or state.get('exit_pending'):return
        worker=subprocess.Popen(['sh',str(BASE/'python.sh'),'-u',str(BASE/'record.py')]+(['--session'] if session else ['--duplex-test'] if duplex else []),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,bufsize=1)
        def deadline():
            if worker and worker.poll() is None:worker.kill()
        timer=None if session else threading.Timer(205,deadline)
        if timer:timer.start()
        try:
            for line in worker.stdout:
                log.write(line);log.flush()
                if not line.startswith('WEB_EVENT '):continue
                e=json.loads(line[10:])
                with LOCK:
                    if e['state']=='saved':
                        p=Path(e['file']).resolve()
                        if p.parent.parent!=DATA/'recordings':raise ValueError('Unexpected recording location')
                        latest=p
                        tmp=DATA/'latest.tmp';tmp.write_text(json.dumps({'file':str(p)}));tmp.replace(DATA/'latest.json')
                        state.update(available=True,seconds=e['seconds'])
                    else:state['state']=e['state']
                    for key in ('session','recording','playing'):
                        if key in e:state[key]=e[key]
                    if e['state']=='restoring':state.update(session=False,recording=False,playing=False)
                    if 'message' in e:state['error']=e['message']
                if e['state'] in ('complete','error'):worker.stdin.close()
            if worker.wait()!=0:raise RuntimeError('Recording failed; automatic recovery remains armed')
        finally:
            if timer:timer.cancel()
    except Exception as e:
        message=str(e)
        if Path('/var/local/kt3-hfp-lab/session-lock').exists():
            with LOCK:state.update(state='restoring',error=message)
            end=time.monotonic()+190
            while time.monotonic()<end and Path('/var/local/kt3-hfp-lab/session-lock').exists():time.sleep(2)
            if not Path('/var/local/kt3-hfp-lab/session-lock').exists():message='Session ended; native audio recovery finished. Inspect status before retrying.'
        with LOCK:state.update(state='error',error=message)
    finally:
        worker=None;log.close()
        with LOCK:
            state.update(busy=False,session=False,recording=False,playing=False)
            if Path('/var/local/kt3-hfp-lab/recovery-failed').exists():state['audio_disabled']=True
def task(action):
    try:
        if action in ('record','duplex','session'):record(action=='duplex',action=='session');return
        if action in ('play','test'):
            connect()
            cmd('mplay',str(latest) if action=='play' else '/var/local/kt3-audio/tone.wav',timeout=30)
        elif action=='connect':connect()
        elif action=='pair':
            audio_ready()
            setprop('com.lab126.pillow','customDialog',json.dumps({'name':'bt_wizard_dialog','clientParams':{'show':True}}))
        elif action=='library':setprop('com.lab126.appmgrd','start','app://com.lab126.booklet.home')
        elif action=='settings':setprop('com.lab126.appmgrd','start','app://com.lab126.booklet.settings')
        elif action=='sleep':setprop('com.lab126.powerd','powerButton','1')
        elif action=='rollback':
            subprocess.Popen(['sh','-c','sleep 1; exec sh /opt/kt3-home/app/disable.sh'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        else:raise ValueError('Unknown action')
        with LOCK:state.update(state='complete',error='')
    except Exception as e:
        with LOCK:state.update(state='error',error=str(e))
    finally:
        with LOCK:state['busy']=False

def exit_home():
    """Close a live session before stopping the service; never kill recovery."""
    sent=False
    end=time.monotonic()+220
    while time.monotonic()<end:
        current=worker
        if current and current.poll() is None and not sent:
            try:current.stdin.write('close\n');current.stdin.flush();sent=True
            except (BrokenPipeError,ValueError):pass
        with LOCK:busy=state['busy']
        if not busy and not Path('/var/local/kt3-hfp-lab/session-lock').exists():
            subprocess.Popen(['sh','/opt/kt3-home/app/disable.sh'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            return
        time.sleep(.5)
    with LOCK:state.update(exit_pending=False,error='Recovery still pending; service left running for safety.')

def auto_connect_loop():
    """One worker at a time; absent earbuds never trigger rapid reconnect loops."""
    delay=2
    while True:
        AUTO_WAKE.wait(delay);AUTO_WAKE.clear()
        with LOCK:
            if not state.get('auto_connect') or state.get('exit_pending') or state.get('audio_disabled') or state['busy']:
                delay=2;continue
            state.update(busy=True,state='connecting',error='',session=False,recording=False,playing=False)
        started=time.monotonic()
        record(session=True)
        with LOCK:
            if state.get('auto_connect') and not state.get('audio_disabled') and not state.get('exit_pending'):
                state['state']='waiting'
        delay=15 if time.monotonic()-started>60 else min(max(delay*2,15),60)

def exit_request_loop():
    """KUAL's existing fixed Exit action may request orderly session shutdown."""
    marker=DATA/'exit-request'
    while True:
        time.sleep(1)
        if not marker.exists():continue
        marker.unlink(missing_ok=True)
        with LOCK:
            if state.get('exit_pending'):continue
            state.update(auto_connect=False,exit_pending=True)
        exit_home()
        return

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,code,data,kind='application/json'):
        if not isinstance(data,bytes):data=json.dumps(data).encode()
        self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass
    def valid(self):return self.client_address[0]=='127.0.0.1' and self.headers.get('Host') in ('localhost:8083','127.0.0.1:8083')
    def do_GET(self):
        if not self.valid():return self.reply(403,{})
        route=self.path.split('?')[0]
        if route in ('/','/index.html','/legacy'):
            return self.reply(200,(BASE/('index.html' if route=='/legacy' else 'home-v2.html')).read_text().replace('__TOKEN__',TOKEN).encode(),'text/html; charset=utf-8')
        if route=='/probe.txt':return self.reply(200,b'KT3_OK','text/plain')
        if route=='/api/text/status':return self.reply(200,text_chat.status())
        if route=='/api/audio/status':
            with LOCK:return self.reply(200,state.copy())
        if route in ('/api/memos','/api/media','/api/media/status','/api/ai/status'):
            try:return self.reply(200,features.get(route,parse_qs(urlsplit(self.path).query)))
            except (ValueError,OSError):return self.reply(400,{'error':'Cannot read local data'})
        if route=='/api/devices':
            devices=[]
            for d in ET.parse('/var/local/zbluetooth/bt_devices.xml').findall('.//device'):
                address=d.findtext('bd_addr','').rstrip(':')
                devices.append({'address':address,'name':d.findtext('device_name') or address})
            return self.reply(200,{'devices':devices,'selected':(DATA/'target.txt').read_text().strip()})
        if route=='/cgi-bin/report.sh':
            q=parse_qs(urlsplit(self.path).query)
            entry={'time':time.time(),'action':q.get('action',[''])[0][:40],'xhr':q.get('xhr',[''])[0][:40]}
            with (DATA/'logs'/'page-events.jsonl').open('a') as f:f.write(json.dumps(entry)+'\n')
            return self.reply(204,b'')
        return self.reply(404,{})
    def do_POST(self):
        global worker
        if not self.valid() or self.headers.get('X-KT3-Token')!=TOKEN:return self.reply(403,{})
        route=self.path.split('?')[0]
        action=route.rsplit('/',1)[-1]
        if route in ('/api/menu/deepseek','/api/menu/qqmusic'):
            def official():
                url='https%3A%2F%2Fy.qq.com%2F' if route.endswith('qqmusic') else 'https%3A%2F%2Fchat.deepseek.com%2F'
                try:setprop('com.lab126.appmgrd','start','app://com.lab126.browser?view='+url)
                except Exception:pass
            threading.Thread(target=official,daemon=True).start()
            return self.reply(202,{'ok':True})
        if route=='/api/menu/previous':
            features.cancel.set()
            if not Path('/opt/kt3-home/rollback-text-music.sh').exists():return self.reply(404,{'error':'Previous version backup unavailable'})
            subprocess.Popen(['sh','/opt/kt3-home/rollback-text-music.sh'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            return self.reply(202,{'ok':True})
        if route in ('/api/text/send','/api/text/clear','/api/memos','/api/media/play','/api/media/cancel','/api/ai/transcribe','/api/ai/chat','/api/ai/cancel'):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<=length<=16384:return self.reply(413,{})
                self.connection.settimeout(5)
                body=json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(body,dict):raise ValueError('Expected object')
                if state.get('exit_pending'):return self.reply(409,{'error':'Home is exiting'})
                if route=='/api/text/send':return self.reply(200,text_chat.send(body.get('text')))
                if route=='/api/text/clear':return self.reply(200,text_chat.clear())
                return self.reply(200,features.post(route,body,latest))
            except (ValueError,KeyError,OSError) as e:return self.reply(400,{'error':str(e)[:140]})
        if route=='/api/menu/rollback':
            features.cancel.set()
            with LOCK:
                state['auto_connect']=False
                if not state.get('exit_pending'):
                    state['exit_pending']=True
                    threading.Thread(target=exit_home,daemon=True).start()
                return self.reply(202,state.copy())
        if route=='/api/menu/library':
            def library():
                try:setprop('com.lab126.appmgrd','start','app://com.lab126.booklet.home')
                except Exception as e:
                    with LOCK:state['error']=str(e)
            threading.Thread(target=library,daemon=True).start()
            return self.reply(202,{'ok':True})
        if state.get('audio_disabled') and (route.startswith('/api/audio/') or route.startswith('/api/session/') or route in ('/api/menu/connect','/api/menu/pair')):
            return self.reply(503,{'error':state['error']})
        if route=='/api/audio/session':
            with LOCK:state['auto_connect']=True
            AUTO_WAKE.set()
            return self.reply(202,state.copy())
        if route=='/api/session/close':
            with LOCK:
                state['auto_connect']=False
                if worker and worker.poll() is None:
                    try:worker.stdin.write('close\n');worker.stdin.flush()
                    except (BrokenPipeError,ValueError):pass
                return self.reply(202,state.copy())
        if route in ['/api/session/'+s for s in ('record','stop','play','stop_play','close')]:
            with LOCK:
                if not state['session'] or not worker or worker.poll() is not None:return self.reply(409,state.copy())
                if action=='play' and not latest:return self.reply(404,{'error':'No recording'})
                try:worker.stdin.write(action+'\n');worker.stdin.flush()
                except (BrokenPipeError,ValueError):return self.reply(409,state.copy())
                return self.reply(202,state.copy())
        if route=='/api/select':
            if int(self.headers.get('Content-Length','0'))>200:return self.reply(413,{})
            try:
                address=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))['address']
                allowed={d.findtext('bd_addr','').rstrip(':') for d in ET.parse('/var/local/zbluetooth/bt_devices.xml').findall('.//device')}
                if address not in allowed:raise ValueError()
                with LOCK:
                    if state['busy']:return self.reply(409,state.copy())
                    (DATA/'target.txt').write_text(address)
                    Path('/var/local/kt3-hfp-lab/target').write_text(address)
                return self.reply(200,{'ok':True})
            except (ValueError,KeyError):return self.reply(400,{})
        if action=='stop' and route=='/api/audio/stop':
            if worker and worker.poll() is None:
                try:worker.stdin.write('stop\n');worker.stdin.flush()
                except (BrokenPipeError,ValueError):pass
            return self.reply(200,state.copy())
        if route not in ['/api/audio/'+s for s in ('record','duplex','session','play','test')]+['/api/menu/'+s for s in ('connect','pair','library','settings','sleep','rollback')]:return self.reply(404,{})
        with LOCK:
            if state['busy']:return self.reply(409,state.copy())
            if action in ('play','duplex') and not latest:return self.reply(404,{'error':'No recording'})
            state.update(busy=True,state='connecting' if action in ('record','duplex','session','connect','pair') else 'playing',error='',session=action=='session',recording=False,playing=False)
        threading.Thread(target=task,args=(action,),daemon=True).start()
        return self.reply(202,state.copy())
if __name__=='__main__':
    (DATA/'logs').mkdir(exist_ok=True);(DATA/'recordings').mkdir(exist_ok=True)
    threading.Thread(target=auto_connect_loop,daemon=True).start()
    threading.Thread(target=exit_request_loop,daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1',8083),Handler).serve_forever()
