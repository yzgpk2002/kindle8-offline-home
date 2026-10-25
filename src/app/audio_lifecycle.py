"""Bounded native-stack recovery; never restart framework, deviced or the device."""
import json,os,signal,subprocess,sys,time,uuid
from pathlib import Path
D=Path('/var/local/kt3-hfp-lab')
BOOT=Path('/proc/sys/kernel/random/boot_id')
BASE=Path('/opt/kt3-home/app')
HEARTBEAT_DIR=Path('/tmp')
os.environ['PATH']='/usr/bin:/bin:/usr/sbin:/sbin'

def run(*args,timeout=12,check=True):
    p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    try:out=p.communicate(timeout=timeout)[0].decode(errors='replace').strip()
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGKILL);p.communicate();raise RuntimeError('Timed out: '+args[0])
    if check and p.returncode:raise RuntimeError('Command failed: '+' '.join(args[:3])+' '+out[:200])
    return out

def prop(source,name):return run('lipc-get-prop',source,name,timeout=3)
def setprop(source,name,value):return run('lipc-set-prop',source,name,str(value),timeout=5)
def identity(pid):
    try:
        p=Path('/proc')/str(int(pid))
        # starttime is field 22; comm may contain spaces.
        start=(p/'stat').read_text().rsplit(')',1)[1].split()[19]
        return {'pid':int(pid),'start':start,'comm':(p/'comm').read_text().strip()}
    except (OSError,ValueError,IndexError):return None
def same(saved):return bool(saved) and identity(saved['pid'])==saved
def load():return json.loads((D/'session.json').read_text())
def valid(s,token):return s['boot']==BOOT.read_text().strip() and s['token']==token
def signal_saved(saved,sig):
    if same(saved):os.kill(saved['pid'],sig)
def save(s):
    p=D/'session.tmp';p.write_text(json.dumps(s));p.replace(D/'session.json')
def heartbeat_path(token):return HEARTBEAT_DIR/('kt3-voice-'+token+'.lease')
def heartbeat(token):
    # /tmp is RAM-backed; avoid periodic writes to Kindle flash storage.
    p=heartbeat_path(token);q=p.with_suffix('.new')
    q.write_text(str(time.monotonic()));q.replace(p)

def query_service_health(token):
    s=load()
    if not valid(s,token):raise RuntimeError('Wrong query-service session')
    if s.get('query_proxy') and not same(s['query_proxy']):
        raise RuntimeError('Bluetooth UI query service exited')

def handoff_queries():
    s=load()
    if s.get('finished') or s.get('query_mode') or not same(s.get('worker')):
        raise RuntimeError('Query handoff requires a fresh live session')
    # The custom native daemon is standalone. Never kill an Upstart-owned daemon:
    # that could respawn and compete for the controller during this handoff.
    if 'stop/waiting' not in run('initctl','status','btfd'):
        raise RuntimeError('Native BTFD is managed by Upstart; handoff refused')
    if not same(s['processes']['btfd']):raise RuntimeError('BTFD identity changed')
    s['query_mode']='lua-v1';save(s)
    signal_saved(s['processes']['btfd'],signal.SIGKILL)
    end=time.monotonic()+3
    while same(s['processes']['btfd']) and time.monotonic()<end:time.sleep(.1)
    if same(s['processes']['btfd']):raise RuntimeError('BTFD did not exit')
    with (D/'query-service.log').open('a') as log:
        p=subprocess.Popen(['/usr/bin/lua',str(BASE/'bt-query-service.lua'),str(s.get('audible',0))],
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    s['query_proxy']=identity(p.pid);save(s)
    if not s['query_proxy'] or not waitprop('com.lab126.btfd','kt3HfpOwner',1,5):
        raise RuntimeError('Bluetooth UI query service did not become ready')
    print('QUERY_HANDOFF_READY',flush=True)

def restore_queries(s):
    if not s.get('query_mode'):return
    # A fresh BTFD has no record of the old A2DP backend. Stop that backend
    # explicitly while the read-only query service cannot restart it.
    for name in ('btd','audiomgrd'):
        if 'stop/waiting' not in run('initctl','status',name):
            run('initctl','stop',name,timeout=10)
    end=time.monotonic()+16
    settled=None
    while time.monotonic()<end:
        stopped=all('stop/waiting' in run('initctl','status',name) for name in ('btd','audiomgrd'))
        now=time.monotonic()
        if stopped:
            if settled is None:settled=now
            if now-settled>=2:break
        else:settled=None
        time.sleep(.25)
    else:raise RuntimeError('Old audio backend did not stop before BTFD replacement')
    proxy=s.get('query_proxy')
    signal_saved(proxy,signal.SIGTERM)
    end=time.monotonic()+3
    while same(proxy) and time.monotonic()<end:time.sleep(.1)
    if same(proxy):
        signal_saved(proxy,signal.SIGKILL);time.sleep(.2)
    if same(proxy):raise RuntimeError('Query service did not stop')
    run('sh','/opt/kt3-home/audio/start-experiment.sh',timeout=15)
    # A fresh native daemon must actually answer, not merely have a process ID.
    prop('com.lab126.btfd','isAudibleAvailable')
def lease_expired(s,started,now):
    try:last=float(heartbeat_path(s['token']).read_text())
    except (OSError,ValueError):return now-started>120
    return last>now or now-last>12
def waitprop(source,name,value,seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            if prop(source,name)==str(value):return True
        except RuntimeError:pass
        time.sleep(.5)
    return False

def native_ready():
    # Pre-start and await the full init before BTFD's one-second startup window.
    if 'start/running' not in run('initctl','status','audiomgrd',check=False):
        run('initctl','start','audiomgrd')
    if not waitprop('com.lab126.audiomgrd','isStarted',1,16):
        raise RuntimeError('Audio manager not ready; no further Bluetooth restart attempted')

def restore_power(s):
    # Old sessions owned this global flag. New sessions leave it untouched so
    # a persistent headset connection does not disable the physical power key.
    if s.get('power_overridden',True):
        setprop('com.lab126.powerd','preventScreenSaver',s['power'])

def wait_native_stopped(seconds=16,stable_seconds=2):
    # BTenable returns before BTFD drains its asynchronous teardown callbacks.
    # A single stop/waiting sample can race a late callback that kills the newly
    # started mixer. Require the controller and both services to remain off.
    end=time.monotonic()+seconds
    settled=None
    while time.monotonic()<end:
        try:
            off=(prop('com.lab126.btfd','BTstate')=='0' and
                 'stop/waiting' in run('initctl','status','btd',check=False) and
                 'stop/waiting' in run('initctl','status','audiomgrd',check=False))
        except RuntimeError:off=False
        now=time.monotonic()
        if off:
            if settled is None:settled=now
            if now-settled>=stable_seconds:return
        else:settled=None
        time.sleep(.25)
    raise RuntimeError('Native stack did not settle off; refusing repeated restart')

def prepare(worker):
    if (D/'recovery-failed').exists():raise RuntimeError('Previous recovery needs inspection')
    if prop('com.lab126.audiomgrd','audioOutputConnected')!='1':raise RuntimeError('Headphones not connected')
    # This property is absent on KT3; an immediate error is fine, a timeout is not.
    result=run('lipc-get-prop','com.lab126.deviced','usbaudioConnected',timeout=3,check=False)
    s={'boot':BOOT.read_text().strip(),'token':uuid.uuid4().hex,'worker':identity(worker),
       'power':prop('com.lab126.powerd','preventScreenSaver'),'power_overridden':False,'processes':{},'phase':'prepared'}
    s['audible']=int(prop('com.lab126.btfd','isAudibleAvailable'))
    if not s['worker'] or s['power'] not in ('0','1'):raise RuntimeError('Invalid initial state')
    for name in ('btfd','btd','bsa_server'):
        pid=run('pidof',name)
        if not pid.isdigit():raise RuntimeError('Expected one '+name)
        s['processes'][name]=identity(pid)
    if (D/'restore-lock').exists():
        old=load()
        if not old.get('finished'):raise RuntimeError('Recovery still pending')
        (D/'restore-lock').rmdir()
    (D/'session-lock').mkdir()
    try:
        for name in ('reader.pid','bridge.pid','tty.state'):(D/name).unlink(missing_ok=True)
        save(s);(D/'restored').unlink(missing_ok=True)
        (D/'power-before').write_text(s['power'])
        with (D/'watchdog.log').open('a') as log:
            p=subprocess.Popen(['sh',str(BASE/'python.sh'),str(BASE/'audio_lifecycle.py'),'watchdog',s['token']],
                               stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        (D/'watchdog.pid').write_text(str(p.pid));print(s['token'],flush=True)
    except BaseException:
        restore_power(s)
        (D/'session-lock').rmdir();raise

def restore(token,kill_worker=False):
    s=load()
    if not valid(s,token) or s.get('finished'):return
    try:(D/'restore-lock').mkdir()
    except FileExistsError:
        for _ in range(70):
            time.sleep(1)
            current=load()
            if current.get('finished'):
                if not current.get('ok'):raise RuntimeError(current.get('error','Recovery failed'))
                return
        raise RuntimeError('Another recovery did not finish')
    s.update(phase='restoring',restorer=identity(os.getpid()),restore_started=time.monotonic());save(s)
    error=None
    try:
        if kill_worker:
            signal_saved(s['worker'],signal.SIGTERM)
            # A stopped event loop must be resumed to receive its termination.
            signal_saved(s['worker'],signal.SIGCONT)
            time.sleep(.2)
            if same(s['worker']):signal_saved(s['worker'],signal.SIGKILL)
        # PIDs are used only with matching executable and current boot/session.
        for name,needle in (('reader','ttymxc2'),('bridge','hfp-bridge.sh')):
            p=D/(name+'.pid')
            if not p.exists():continue
            pid=p.read_text().strip()
            if not pid.isdigit():continue
            try:cmd=(Path('/proc')/pid/'cmdline').read_bytes().replace(b'\0',b' ').decode()
            except OSError:continue
            if needle in cmd:os.kill(int(pid),signal.SIGTERM)
        time.sleep(.5)
        if (D/'tty.state').exists():run('stty','-F','/dev/ttymxc2',(D/'tty.state').read_text().strip(),timeout=3)
        for name in ('btd','btfd'):signal_saved(s['processes'][name],signal.SIGCONT)
        restore_queries(s)
        if not s.get('query_mode'):
            setprop('com.lab126.btfd','BTenable','0:2')
            wait_native_stopped()
        # query_mode already stopped the old backend before starting fresh BTFD.
        # Do not issue OFF during that daemon's asynchronous initial ON request.
        native_ready()
        setprop('com.lab126.btfd','BTenable','1:2')
        if not waitprop('com.lab126.btmd','Enable',2,12):raise RuntimeError('Bluetooth stack not ready')
        end=time.monotonic()+8
        while prop('com.lab126.btfd','BTstate') not in ('1','2'):
            if time.monotonic()>=end:raise RuntimeError('Bluetooth controller not ready')
            time.sleep(.5)
        time.sleep(.5)
        target=(D/'target').read_text().strip()
        try:setprop('com.lab126.btfd','Connect',target)
        except RuntimeError:
            if prop('com.lab126.audiomgrd','isStarted')!='1':raise
        # Returning earbuds to their case is normal: distinguish a healthy native
        # stack without a headset from a failed audio-manager recovery.
        connected=waitprop('com.lab126.audiomgrd','audioOutputConnected',1,15)
        if not connected and prop('com.lab126.audiomgrd','isStarted')!='1':
            raise RuntimeError('Native audio manager failed during reconnect')
        s['headset_connected']=connected
        (D/'restored').touch()
    except Exception as e:
        error=str(e);(D/'recovery-failed').write_text(error)
        print('RESTORE_FAILED',error,flush=True)
    finally:
        # No stopped native processes are left behind, even after a failed reconnect.
        for name in ('btd','btfd'):signal_saved(s['processes'][name],signal.SIGCONT)
        try:restore_power(s)
        except Exception as e:print('POWER_RESTORE_FAILED',str(e),flush=True)
        s.update(finished=True,ok=error is None,error=error);save(s)
        (D/'session-lock').rmdir()
        (D/'restore-lock').rmdir()
        heartbeat_path(token).unlink(missing_ok=True)
    if error:raise RuntimeError(error)
    print('RESTORED',token,flush=True)

def watchdog(token,seconds=None):
    # Old timers cannot act on a later session or a different boot.
    started=time.monotonic()
    while True:
        time.sleep(1)
        s=load()
        if not valid(s,token) or s.get('finished'):return
        if s.get('phase')=='restoring':
            if same(s.get('restorer')) and time.monotonic()-s['restore_started']<90:continue
            # The bounded normal recovery died. Retry once with the same session
            # identity after terminating only its verified recovery process.
            signal_saved(s.get('restorer'),signal.SIGTERM)
            time.sleep(.5)
            try:(D/'restore-lock').rmdir()
            except FileNotFoundError:pass
            break
        if seconds is not None:
            if time.monotonic()-started>=seconds:break
        elif not same(s.get('worker')) or lease_expired(s,started,time.monotonic()):break
    restore(token,kill_worker=True)

def startup():
    if not (D/'session-lock').exists():return
    s=load()
    if s['boot']==BOOT.read_text().strip():raise RuntimeError('A current-boot session still needs recovery')
    # A new boot invalidates all saved PIDs. Never signal them or restore old power state.
    archive=D/('interrupted-'+s['token']+'.json')
    archive.write_text(json.dumps(s))
    if (D/'restore-lock').exists():(D/'restore-lock').rmdir()
    (D/'session-lock').rmdir()
    (D/'recovery-failed').write_text('Interrupted previous-boot session archived; audio needs inspection.')

if __name__=='__main__':
    action=sys.argv[1]
    if action=='prepare':prepare(int(sys.argv[2]))
    elif action=='watchdog':watchdog(sys.argv[2])
    elif action=='restore':restore(sys.argv[2] if len(sys.argv)>2 else load()['token'])
    elif action=='native-ready':native_ready()
    elif action=='startup':startup()
    elif action=='handoff-queries':handoff_queries()
    else:raise ValueError('Unknown action')
