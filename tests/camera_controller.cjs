/* Offline browser-contract test. No physical camera or platform requests. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const SignCameraQueue=require('../web/camera-queue.js');
const elements=new Map(),users=[{value:'a',checked:true},{value:'b',checked:true}];
function element(key){
  if(!elements.has(key))elements.set(key,{textContent:'',innerHTML:'',dataset:{},value:'environment',replaceChildren(){},
    pause(){},play:async()=>{},readyState:2,videoWidth:4,videoHeight:4});
  return elements.get(key);
}
const requests=[],pending=[],workers=[],streams=[];let permissions=0,now=100000;
function stream(){const track={stops:0,stop(){this.stops++;},addEventListener(){}};const value={track,getTracks:()=>[track],getVideoTracks:()=>[track]};streams.push(value);return value;}
const events={};
const context=vm.createContext({SignCameraQueue,URL,URLSearchParams,Uint8ClampedArray,Set,Map,Promise,console,
  Date:class extends Date{static now(){return now;}},
  state:{page:'sign-camera',accounts:[{id:'a',name:'甲'},{id:'b',name:'乙'}]},
  window:{isSecureContext:true,addEventListener:(name,fn)=>events['window:'+name]=fn},
  navigator:{mediaDevices:{getUserMedia:async constraints=>{permissions++;assert.equal(constraints.audio,false);return stream();}}},
  document:{hidden:false,addEventListener:(name,fn)=>events[name]=fn,createElement:()=>({getContext:()=>({drawImage(){},getImageData:()=>({data:new Uint8ClampedArray(64)})})})},
  $:selector=>element(selector),
  $$:selector=>selector==='[name="camera-user"]:checked'?users.filter(a=>a.checked):selector.includes('camera-user')?users:[],
  esc:value=>String(value),heading:()=>'',button:()=>'',
  setTimeout:()=>1,clearTimeout:()=>{},
  Worker:class{constructor(){workers.push(this);}postMessage(){}terminate(){this.terminated=true;}},
  api:(path,method,body)=>{requests.push({path,method,body});return new Promise((resolve,reject)=>pending.push({resolve,reject}));}
});
vm.runInContext(fs.readFileSync('web/camera-sign.js','utf8'),context);
const get=expression=>vm.runInContext(expression,context);
const flush=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();};
const qr=enc=>'https://mobilelearn.chaoxing.com/widget/sign/e?id=902&enc='+enc;
const frame=(worker,text)=>{get(`cameraSession.frameAt=${now}`);worker.onmessage({data:{text}});};

(async()=>{
  assert.equal(permissions,0,'Loading a page must not request camera permission');
  users.forEach(a=>a.checked=false);await get('startSignCamera()');assert.equal(permissions,0);
  assert.match(element('#camera-error').textContent,/至少/);
  users.forEach(a=>a.checked=true);context.window.isSecureContext=false;await get('startSignCamera()');
  assert.equal(permissions,0);assert.match(element('#camera-error').textContent,/HTTPS/);
  context.window.isSecureContext=true;await get('startSignCamera()');
  assert.equal(permissions,1);assert.equal(get('cameraSession.running'),true);
  const worker=workers.at(-1);
  frame(worker,qr('OFFLINE_FIRST_TOKEN'));
  assert.equal(requests.length,1);assert.match(requests[0].path,/\/a\/camera-sign$/);
  frame(worker,qr('OFFLINE_CHANGED_TOKEN'));
  assert.equal(requests.length,1,'Users must never be submitted concurrently');
  pending[0].resolve({message:'成功'});await flush();now+=1000;
  frame(worker,qr('OFFLINE_LATEST_TOKEN'));
  assert.equal(requests.length,2);assert.match(requests[1].path,/\/b\/camera-sign$/);
  assert.equal(requests[1].body.qr,qr('OFFLINE_LATEST_TOKEN'),'Next user must use a fresh frame');
  pending[1].resolve({message:'成功'});await flush();
  assert.equal(get('cameraSession.queue.done'),true);assert.equal(get('cameraSession.running'),false);
  assert.equal(streams[0].track.stops,1);assert.equal(worker.terminated,true);assert.equal(element('#sign-camera-video').srcObject,null);

  await get('startSignCamera()');const second=workers.at(-1);
  frame(second,qr('OFFLINE_FAIL_TOKEN'));
  pending[2].reject(Object.assign(new Error('过期'),{status:502}));await flush();
  assert.equal(get('cameraSession.queue.current.failures'),1);
  frame(second,qr('OFFLINE_FAIL_TOKEN'));assert.equal(requests.length,3,'Failures need a retry interval');
  now+=3000;frame(second,'');assert.equal(requests.length,3,'Blank frames must not reuse an old QR');
  frame(second,qr('OFFLINE_NEXT_TOKEN').replace('id=902','id=903'));assert.equal(requests.length,3,'Do not switch activity mid-queue');
  get(`cameraSession.frameAt=${now-2000}`);second.onmessage({data:{text:qr('OFFLINE_OLD_FRAME')}});
  assert.equal(requests.length,3,'Slow decoding must not turn an old frame into a fresh QR');
  frame(second,qr('OFFLINE_NEXT_TOKEN'));assert.equal(requests.length,4);
  get("closeSignCamera('用户停止')");assert.equal(streams[1].track.stops,1);
  pending[3].resolve({message:'成功'});await flush();assert.equal(get('cameraSession.running'),false);
  second.onmessage({data:{text:qr('OFFLINE_AFTER_STOP')}});assert.equal(requests.length,4);
  assert.equal(get('cameraSession.queue.entries[0].status'),'succeeded','An in-flight success is still displayed after stopping');

  let allow;
  context.navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>allow=resolve);
  const starting=get('startSignCamera()');get("closeSignCamera('取消权限等待')");
  const late=stream();allow(late);await starting;
  assert.equal(late.track.stops,1,'Late permission grants must immediately release tracks');
  assert.equal(get('cameraSession.running'),false);

  context.navigator.mediaDevices.getUserMedia=async()=>stream();await get('startSignCamera()');
  context.document.hidden=true;events.visibilitychange();
  assert.equal(streams.at(-1).track.stops,1);assert.equal(get('cameraSession.running'),false);
  console.log('camera controller contract passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
