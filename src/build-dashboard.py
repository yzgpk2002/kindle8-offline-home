from pathlib import Path
import re
p=Path(__file__).resolve().parent
old=(p/'home-before-dashboard.html').read_text(encoding='utf-8')
js=re.search(r'<script>([\s\S]*?)</script>',old).group(1)
# Keep the accepted audio commands, WAF hooks and polling. Replace memo/view layout.
start=js.index("try{el('memo').value=");end=js.index("window.onunload=",start)
js=js[:start]+(p/'dashboard.js').read_text(encoding='utf-8')+'\n'+js[end:]
js=js.replace("clearTimeout(timer);}\nfunction resumePage", "clearTimeout(timer);clearTimeout(textTimer);}\nfunction resumePage")
js=js.replace("clearTimeout(timer);poll();}","clearTimeout(timer);poll();if(textBusy)textStatus();}")
js=js.replace("put('audioStatus',text);", "text=s.recording?'正在录音 · 最长15秒':s.playing?'正在播放':ready?'耳机已连接':s.audio_disabled?'音频暂不可用':s.exit_pending?'正在退出':s.state==='restoring'?'正在释放音频':s.auto_connect?'等待耳机连接':'连接已暂停';put('audioStatus',text);")
page=(p/'dashboard.html').read_text(encoding='utf-8').replace('__SCRIPT__',js)
(p/'app/home-v2.html').write_text(page,encoding='utf-8',newline='\n')
exec(compile((p/'build-offline-home.py').read_text(encoding='utf-8'),str(p/'build-offline-home.py'),'exec'))
