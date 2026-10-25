const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(__dirname+'/../src/app/home-offline.html','utf8');
let status={state:'waiting_headset',auto_connect:true,session:false},nextId=1,requests=0;
const timers=new Map(),elements=new Map(),contexts=[],kindle={appmgr:{saveContext(value){contexts.push(value);}}};
function element(id){if(!elements.has(id))elements.set(id,{textContent:'',value:'',disabled:false,className:'',appendChild(){}});return elements.get(id);}
function XHR(){this.open=(method,path)=>{this.path=path;};this.setRequestHeader=()=>{};this.abort=()=>{};this.send=()=>{requests++;this.status=200;this.readyState=4;this.responseText=JSON.stringify(this.path.includes('/api/memos')?{memos:{}}:this.path.includes('/api/ai/status')?{state:'unconfigured'}:status);this.onreadystatechange();};}
const context={document:{getElementById:element,createElement:()=>({})},window:{scrollTo(){}},kindle,Image:function(){},XMLHttpRequest:XHR,
 localStorage:{getItem:()=>null,setItem(){}},Date,JSON,encodeURIComponent,
 setTimeout(fn,delay){const id=nextId++;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);}};
vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
assert.equal(element('record').disabled,true);
let poll=[...timers.values()][0];assert.equal(poll.delay,1000,'reconnect must not leave buttons stale for ten seconds');
status={state:'session_ready',auto_connect:true,session:true,recording:false,playing:false,available:true};
poll.fn();assert.equal(element('record').disabled,false);
kindle.appmgr.onpause();assert.equal(timers.size,0);
let before=requests;kindle.appmgr.ongo();assert.equal(requests,before+1,'returning to page must refresh immediately');
assert.deepEqual(contexts,['page=voice'],'foreground callback must acknowledge application context');
assert.equal([...timers.values()][0].delay,250);
console.log('PASS reconnect buttons refresh within one poll; background pause and foreground resume');
assert.match(element('month0').innerHTML,/data-day=/);
assert.match(element('month1').innerHTML,/data-day=/);
element('memo').value='test';element('memo').oninput();element('save').onclick();
assert.equal(element('saveStatus').textContent,'已保存');
const oldMonth=element('month0').innerHTML;element('next').onclick();assert.notEqual(element('month0').innerHTML,oldMonth);
console.log('PASS two months, month navigation and server memo save');
