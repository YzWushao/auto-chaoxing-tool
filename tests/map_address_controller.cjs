const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const flush=()=>new Promise(resolve=>setImmediate(resolve)),timers=new Map(),requests=[],pending=[],messages=[];
let serial=0;const field={value:''},provider={value:'amap'},map={reverse:point=>{requests.push(point);return new Promise(resolve=>pending.push(resolve));}};
const state={map_settings:{free_reverse_enabled:false},signMap:map};
const ctx=vm.createContext({state,Map,AbortController,console,document:{addEventListener(){}},
 $:s=>s==='#sign-address'?field:s==='#sign-map-provider'?provider:null,
 signMapStatus:m=>messages.push(m),presetMapStatus:m=>messages.push(m),
 setTimeout:fn=>{timers.set(++serial,fn);return serial;},clearTimeout:id=>timers.delete(id),
 api:()=>{throw new Error('Unexpected external lookup');}});
vm.runInContext(fs.readFileSync('web/map-address.js','utf8'),ctx);
const run=s=>vm.runInContext(s,ctx),point=lng=>{state.signMapPoint={lng,lat:30};ctx.point=state.signMapPoint;run("MapAddressLookup.queue('sign',point)");};
const fire=()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);void fn();};
(async()=>{
 point(116);assert.equal(requests.length,0);fire();assert.equal(requests.length,1);
 point(117);pending[0]({address:'旧地址'});await flush();assert.equal(field.value,'');
 fire();pending[1]({address:'新地址'});await flush();assert.equal(field.value,'新地址');
 point(118);assert.equal(field.value,'');fire();field.value='手动地址';pending[2]({address:'服务器地址'});await flush();assert.equal(field.value,'手动地址');
 point(119);assert.equal(timers.size,0,'Manual text must be preserved');
 field.value='地图选点（116, 30）';point(120);fire();run("MapAddressLookup.cancel('sign')");pending[3]({address:'已关闭的地址'});await flush();assert.equal(field.value,'');
 provider.value='osm';point(121);assert.equal(timers.size,0);assert(messages.at(-1).includes('开启'));
 provider.value='amap';point(122);fire();pending[4]({address:''});await flush();assert.equal(field.value,'');assert(messages.at(-1).includes('手动填写'));
 console.log('Latest point, cancellation, opt-in and manual address preservation verified');
})().catch(e=>{console.error(e);process.exitCode=1;});
