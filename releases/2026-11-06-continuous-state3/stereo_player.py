import hashlib
import audioop
import os
from pathlib import Path
import subprocess
import threading
import time
import wave
import struct
from contextlib import contextmanager
import queue

class StereoOutput:
    """One 48 kHz stereo mixer stream shared by consecutive tracks."""
    def __init__(self, owner):
        self.owner = owner
        self.items = queue.Queue(maxsize=8)
        self.closed = threading.Event()
        self.error = None
        self.proc = subprocess.Popen(
            ['gst-launch','-q','fdsrc','fd=0','!',
             'audio/x-raw-int,rate=48000,channels=2,width=16,depth=16,signed=true,endianness=1234',
             '!','mixersink'], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.thread = threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def alive(self):
        return not self.closed.is_set() and self.error is None and self.proc.poll() is None

    def submit(self, job, raw, elapsed, done=None):
        while self.owner.job == job:
            if not self.alive():raise ValueError('立体声音频输出已中断，请重新点歌')
            try:
                self.items.put((job,raw,elapsed,done),timeout=.1)
                return
            except queue.Full:pass
        raise InterruptedError()

    def run(self):
        silence = bytes(960*4)
        try:
            while not self.closed.is_set():
                item = None
                if not self.owner.paused:
                    try:item=self.items.get_nowait()
                    except queue.Empty:pass
                if item is None:
                    self.proc.stdin.write(silence)
                    self.proc.stdin.flush()
                    continue
                job,raw,elapsed,done=item
                if job != self.owner.job:
                    if done:done.set()
                    continue
                if done:
                    done.set()
                    continue
                self.proc.stdin.write(audioop.mul(raw,2,self.owner.volume/100))
                self.proc.stdin.flush()
                with self.owner.lock:
                    if job == self.owner.job:
                        self.owner.elapsed = elapsed
                        self.owner.message = '已暂停' if self.owner.paused else '立体声播放中'
        except (OSError,ValueError) as error:
            self.error = error
        finally:
            if self.proc.poll() is None:self.proc.terminate()
            try:self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
            try:self.proc.stdin.close()
            except (OSError,ValueError):pass

    def close(self):
        self.closed.set()
        if self.proc.poll() is None:self.proc.terminate()
        self.thread.join(timeout=4)

class MP3Frames:
    def __init__(self, process):
        self.process = process
        header = process.stdout.read(20)
        if len(header) != 20:raise ValueError('无法读取 MP3 音频信息')
        magic, self.rate, self.channels, self.frames = struct.unpack('<4sIIQ', header)
        if magic != b'KPCM' or not 8000 <= self.rate <= 48000 or self.channels not in (1,2):
            raise ValueError('MP3 音频格式无效')
        self.position = 0

    def getframerate(self):return self.rate
    def getnchannels(self):return self.channels
    def getsampwidth(self):return 2
    def getnframes(self):return self.frames
    def tell(self):return self.position

    def readframes(self, count):
        raw = self.process.stdout.read(count*self.channels*2)
        if len(raw) % (self.channels*2):raise ValueError('MP3 音频帧不完整')
        if not raw and self.process.wait(timeout=5):
            raise ValueError('MP3 解码失败')
        self.position += len(raw)//(self.channels*2)
        return raw

GAIN = Path('/var/local/kt3-home/music-volume')

class StereoPlayer:
    def __init__(self, data):
        self.cache = data / 'stereo-cache'
        self.lock = threading.RLock()
        self.enabled = False
        self.job = 0
        self.output = None
        self.decoder = None
        self.message = '已停止'
        self.title = ''
        self.elapsed = 0
        self.duration = None
        self.paused = False
        self.mode_file = data / 'music-play-mode'
        self.play_mode = self.mode_file.read_text().strip() if self.mode_file.exists() else 'sequence'
        if self.play_mode not in ('single','sequence','shuffle'):self.play_mode='sequence'
        self.volume = int(GAIN.read_text()) if GAIN.exists() else 50

    def status(self):
        with self.lock:
            return dict(stereo=self.enabled, volume=self.volume, message=self.message,
                        title=self.title, elapsed=self.elapsed, duration=self.duration,
                        paused=self.paused, play_mode=self.play_mode)

    def set_play_mode(self, mode):
        if mode not in ('single','sequence','shuffle'):raise ValueError('Invalid play mode')
        with self.lock:
            tmp=self.mode_file.with_suffix('.tmp')
            tmp.write_text(mode)
            tmp.replace(self.mode_file)
            self.play_mode=mode

    def toggle_pause(self):
        with self.lock:
            if self.message not in ('立体声播放中','已暂停'):return
            self.paused = not self.paused
            self.message = '已暂停' if self.paused else '立体声播放中'

    def gain(self, level):
        if type(level) is not int or not 0 <= level <= 100:
            raise ValueError('Invalid volume')
        with self.lock:
            tmp = GAIN.with_suffix('.tmp')
            tmp.write_text(str(level))
            tmp.replace(GAIN)
            self.volume = level

    def stop(self):
        with self.lock:
            self.job += 1
            self.paused = False
            if self.decoder and self.decoder.poll() is None:
                self.decoder.terminate()
            self.message = '已停止'

    def output_alive(self):
        with self.lock:
            return self.output is not None and self.output.alive()

    def close_output(self):
        self.stop()
        with self.lock:
            output,self.output=self.output,None
        if output:output.close()

    @contextmanager
    def source_frames(self, job, source, compressed):
        if not compressed:
            with wave.open(str(source)) as f:
                yield f
            return
        with self.lock:
            if self.job != job:raise InterruptedError()
            decoder = subprocess.Popen(['/opt/kt3-home/app/mp3stream',str(source)],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            self.decoder = decoder
        try:
            yield MP3Frames(decoder)
        finally:
            if decoder.poll() is None:decoder.terminate()
            try:decoder.wait(timeout=3)
            except subprocess.TimeoutExpired:decoder.kill();decoder.wait()
            decoder.stdout.close()
            with self.lock:
                if self.decoder is decoder:self.decoder=None

    def stream(self, job, wav, compressed=False):
        with self.source_frames(job,wav,compressed) as f:
            rate,channels,width = f.getframerate(),f.getnchannels(),f.getsampwidth()
            if channels not in (1,2) or width not in (1,2,3,4):
                raise ValueError('不支持的 PCM 格式')
            with self.lock:
                if self.job != job: raise InterruptedError()
                self.duration = f.getnframes() // rate
                if not self.output_alive():self.output=StereoOutput(self)
                output=self.output
            converter = None
            while self.job == job:
                if self.paused:
                    time.sleep(.02)
                    continue
                raw=f.readframes(1024)
                if not raw:break
                if width==1:raw=audioop.bias(raw,1,-128)
                if width!=2:raw=audioop.lin2lin(raw,width,2)
                if channels==1:raw=audioop.tostereo(raw,2,1,1)
                raw,converter=audioop.ratecv(raw,2,2,rate,48000,converter)
                output.submit(job,raw,f.tell()//rate)
            if self.job != job:return
            done=threading.Event()
            output.submit(job,b'',0,done)
            while not done.wait(.1):
                if self.job != job:return
                if not output.alive():raise ValueError('立体声音频输出已中断，请重新点歌')

    def play(self, source, ready):
        with self.lock:
            self.stop()
            job = self.job
            self.title = source.stem
            self.elapsed = 0
            self.duration = None
            self.message = '等待耳机切换至立体声'
        def run():
            try:
                deadline = time.monotonic() + 220  # Allow the duplex recovery watchdog to finish.
                while time.monotonic() < deadline:
                    if self.job != job: return
                    if ready(): break
                    time.sleep(.5)
                else: raise ValueError('耳机未就绪，请戴好后再点歌')
                compressed = False
                if source.suffix.lower() == '.mp3':
                    self.cache.mkdir(exist_ok=True)
                    key = hashlib.sha256((str(source)+str(source.stat().st_mtime_ns)).encode()).hexdigest()[:20]
                    wav = self.cache/(key+'.wav')
                    if not wav.exists():
                        wav = source
                        compressed = True
                else: wav = source
                self.stream(job,wav,compressed)
                result = '播放结束'
            except Exception as e:
                result = str(e)[:120]
            with self.lock:
                if self.job == job: self.message = result
        threading.Thread(target=run,daemon=True).start()
