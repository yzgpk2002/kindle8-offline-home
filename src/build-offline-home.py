"""Build a local WAF page from the accepted UI without changing the HTTP UI."""
from pathlib import Path
root=Path(__file__).resolve().parent
page=(root/'app/home-v2.html').read_text(encoding='utf-8')
assert page.count('x.open(method,path,true)')==1
page=page.replace('x.open(method,path,true)',"x.open(method,'http://127.0.0.1:8083/'+path,true)")
page=page.replace('(function(){', '(function(){\nvar beacons=[];', 1)
page=page.replace('仅手动启动。当前仍需保持 Wi-Fi 连接。','仅手动启动。本机主页和录音服务不需要 Wi-Fi 或 USB。')
page=page.replace('<p class="small"><a href="legacy">旧版录音测试页</a></p>','')
page=page.replace("function action(path){clearTimeout(timer);", "function action(path){report(path.replace(/\\//g,'-'));clearTimeout(timer);")
page=page.replace("last=s;var ready=", "var wasReady=last.session&&last.state==='session_ready';last=s;var ready=")
page=page.replace("put('audioStatus',text);", "put('audioStatus',text);if(ready&&!wasReady)report('record-ready');")
page=page.replace("var beacon=new Image();beacon.src='cgi-bin/report.sh?action=session-page-v2';", """
function report(s){var b=new Image();beacons.push(b);b.onload=b.onerror=function(){var i=beacons.indexOf(b);if(i>=0)beacons.splice(i,1);};b.src='http://127.0.0.1:8083/cgi-bin/report.sh?action=offline-home&xhr='+encodeURIComponent(s)+'&t='+Date.now();}
function enteredPage(){
 if(typeof kindle.appmgr.saveContext==='function'){kindle.appmgr.saveContext('page=voice');report('context-saved');}
 resumePage();
}
if(typeof kindle!=='undefined'&&kindle.appmgr){kindle.appmgr.onload=resumePage;kindle.appmgr.ongo=enteredPage;kindle.appmgr.onpause=pausePage;kindle.appmgr.onunload=pausePage;}
el('record').onmousedown=function(){report('record-pointer');};
report('loaded');""")
(root/'app/home-offline.html').write_text(page,encoding='utf-8',newline='\n')
