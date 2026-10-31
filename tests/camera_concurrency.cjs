/* Offline concurrency contract: synthetic frames and deferred HTTP responses. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const SignCameraQueue=require('../web/camera-queue.js');
const qr=token=>'https://mobilelearn.chaoxing.com/?id=902&enc=OFFLINE_'+token;
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function harness(count=7,preferences={camera_concurrency:5,camera_scan_interval:0.1}){
  const elements=new Map(),requests=[],pending=[],workers=[],delays=[],tracks=[],verification=[];
  const accounts=Array.from({length:count},(_,i)=>({id:String.fromCharCode(97+i),name:'用户'+i}));
  let now=100000,album='ALBUM_FIRST';
  function el(key){
    if(!elements.has(key))elements.set(key,{textContent:'',innerHTML:'',dataset:{},value:key==='#camera-facing'?'environment':'',
      replaceChildren(){},classList:{add(){},remove(){},toggle(){}},removeAttribute(){},pause(){},play:async()=>{},readyState:2,videoWidth:4,videoHeight:4});
    return elements.get(key);
  }
  const context=vm.createContext({SignCameraQueue,URL,URLSearchParams,Uint8ClampedArray,Set,Map,Promise,console,AbortController,
    SignQR:{decodeImage:async()=>({raw:qr(album),preview:'data:image/png;base64,AAAA'})},
    Date:class extends Date{static now(){return now;}},state:{page:'sign-camera',accounts,preferences},
    window:{isSecureContext:true,addEventListener(){}},
    navigator:{mediaDevices:{getUserMedia:async()=>{const t={stops:0,stop(){this.stops++;},addEventListener(){}};tracks.push(t);return {getTracks:()=>[t],getVideoTracks:()=>[t]};}}},
    document:{addEventListener(){},createElement:()=>({getContext:()=>({drawImage(){},getImageData:()=>({data:new Uint8ClampedArray(64)})})})},
    $:el,$$:selector=>selector==='[name="camera-user"]:checked'?accounts.map(a=>({value:a.id})):[],
    esc:String,heading:()=>'',button:()=>'',clearSignVerification(){},closeSignFace(){},
    showSignVerification:(name,account,value)=>verification.push({account,value}),
    setTimeout:(fn,ms)=>{delays.push(ms);return 1;},clearTimeout(){},
    Worker:class{constructor(){workers.push(this);}postMessage(){}terminate(){this.terminated=true;}},
    api:(path,method,body)=>{requests.push({path,body});return new Promise((resolve,reject)=>pending.push({resolve,reject}));}
  });
  vm.runInContext(fs.readFileSync('web/camera-sign.js','utf8'),context);
  const get=code=>vm.runInContext(code,context);
  return {get,requests,pending,workers,delays,tracks,verification,el,
    advance:ms=>now+=ms,album:value=>album=value,
    frame(token='FRAME'){get(`cameraSession.frameAt=${now}`);workers.at(-1).onmessage({data:{text:qr(token)}});}};
}
const failure=(message='过期')=>Object.assign(new Error(message),{status:502});
const challenge=id=>Object.assign(new Error('滑块验证'),{status:409,code:'verification_required',verification:{id}});

(async()=>{
  const rotating=new SignCameraQueue.Queue(Array.from('abcdef',id=>({id,name:id})),5);
  for(let i=0;i<5;i++)rotating.begin();
  for(let i=0;i<11;i++){
    if(i)assert.equal(rotating.begin('b').id,'b');
    rotating.finish(false,'过期','b');
  }
  assert.deepEqual(rotating.order,['a','c','d','e','f','b']);
  assert.equal(rotating.begin().id,'f','Only the failed account rotates; the other active requests retain their slots');
  rotating.finish(true,'成功','c');assert.equal(rotating.inFlight.has('a'),true);assert.equal(rotating.inFlight.has('c'),false);
  const h=harness();await h.get('startSignCamera()');h.frame();
  assert.equal(h.requests.length,5);assert.equal(h.get('cameraSession.queue.inFlight.size'),5);
  h.frame('CHANGED');assert.equal(h.requests.length,5,'A fresh frame cannot overflow the limit or duplicate an account');
  h.pending[2].resolve({message:'丙成功'});h.pending[0].resolve({message:'甲成功'});await flush();
  assert.equal(h.get("cameraSession.queue.entries.find(e=>e.id==='c').status"),'succeeded');
  assert.equal(h.get("cameraSession.queue.entries.find(e=>e.id==='a').status"),'succeeded');
  h.frame('STILL_BUSY');assert.equal(h.requests.length,5,'The current batch must drain before another starts');
  h.pending[1].reject(failure());h.pending[4].resolve({message:'成功'});h.pending[3].resolve({message:'成功'});await flush();
  h.frame('NEXT_WAVE');assert.equal(h.requests.length,7);
  assert.deepEqual(h.requests.slice(5).map(r=>r.path.split('/')[2]),['f','g']);
  assert.ok(h.requests.slice(5).every(r=>r.body.qr===qr('NEXT_WAVE')),'The next batch uses the latest decoded frame');
  h.pending[5].resolve({message:'成功'});h.pending[6].resolve({message:'成功'});await flush();
  h.frame();assert.equal(h.requests.length,7,'A failed account retains its own cooldown');
  h.advance(2600);h.frame('RETRY_B');assert.equal(h.requests.length,8);assert.match(h.requests[7].path,/\/b\/camera-sign$/);
  h.pending[7].resolve({message:'成功'});await flush();assert.equal(h.get('cameraSession.running'),false);

  const v=harness(5);await v.get('startSignCamera()');v.frame();await flush();
  v.pending[3].reject(Object.assign(new Error('选择位置'),{status:422,code:'location_required'}));
  v.pending[1].reject(Object.assign(new Error('本人照片'),{status:422,code:'face_required',activity:{id:'902',source:'group'}}));
  v.pending[0].reject(challenge('slider-a'));v.pending[4].resolve({message:'成功'});await flush();
  assert.equal(v.verification.length,0,'Do not replace the visible verification while the batch is still returning');
  v.pending[2].resolve({message:'成功'});await flush();
  assert.equal(v.get('cameraSession.attention'),'d',JSON.stringify(v.get('({attention:cameraSession.attention,blocked:cameraSession.blocked.map(b=>b.entry.id),entries:cameraSession.queue.entries})')));assert.equal(v.get('cameraSession.requirement'),'location_required');
  assert.equal(v.get('cameraSession.queue.current.attempts'),0,'Verification requirements do not count as failed attempts');
  v.el('#camera-location').value=JSON.stringify(['离线学校','教学楼']);
  v.get('cameraSession.requirement=null');v.advance(3000);v.frame('WITH_LOCATION');
  assert.equal(v.requests.length,6,'Only the user being assisted is retried');
  assert.equal(v.requests[5].body.location.name,'教学楼');v.pending[5].resolve({message:'成功'});await flush();
  assert.equal(v.get('cameraSession.attention'),'b');assert.equal(v.get('cameraSession.faceTarget.source'),'group');
  v.get("cameraSession.faceProof={id:'photo-b',account:'b'};cameraSession.requirement=null");v.advance(3000);v.frame('FACE_B');
  assert.equal(v.requests[6].body.face_id,'photo-b');v.pending[6].reject(challenge('slider-b'));await flush();
  assert.equal(v.verification.at(-1).account,'b');
  v.get("cameraSession.verification=null;cameraSession.proof={id:'slider-b',account:'b'}");v.advance(3000);v.frame('BOTH_B');
  assert.equal(v.requests[7].body.face_id,'photo-b');assert.equal(v.requests[7].body.verification_id,'slider-b');
  v.pending[7].resolve({message:'成功'});await flush();assert.equal(v.verification.at(-1).account,'a');
  assert.equal(v.get('cameraSession.faceProof'),null);
  v.get("cameraSession.verification=null;cameraSession.proof={id:'slider-a',account:'a'}");v.advance(3000);v.frame('ONLY_A');
  assert.equal(v.requests[8].body.face_id,undefined);assert.equal(v.requests[8].body.verification_id,'slider-a');
  v.pending[8].resolve({message:'成功'});await flush();assert.equal(v.get('cameraSession.queue.done'),true);

  const stop=harness();await stop.get('startSignCamera()');stop.frame();stop.get("closeSignCamera('停止')");
  await stop.get('startSignCamera()');assert.equal(stop.tracks.length,1,'Cannot replace a queue while requests are still in flight');
  stop.pending[0].reject(challenge('late'));stop.pending.slice(1).forEach(p=>p.resolve({message:'成功'}));await flush();
  assert.equal(stop.verification.length,0);assert.equal(stop.get('cameraSession.running'),false);
  assert.equal(stop.get("cameraSession.queue.entries.filter(e=>e.status==='succeeded').length"),4);
  assert.equal(stop.requests.length,5,'Stopping prevents all later batches but retains returning results');

  const album=harness();await album.get('startImageSign({})');assert.equal(album.requests.length,5);
  album.album('ALBUM_UPDATED');await album.get('startImageSign({})');
  album.pending.slice(0,5).forEach(p=>p.resolve({message:'成功'}));await flush();
  album.get('submitCameraNext(cameraSession.generation)');assert.equal(album.requests.length,7);
  assert.ok(album.requests.slice(5).every(r=>r.body.qr===qr('ALBUM_UPDATED')));
  assert.equal(album.tracks.length,0);album.pending.slice(5).forEach(p=>p.resolve({message:'成功'}));await flush();

  const defaults=harness(2,{});await defaults.get('startSignCamera()');defaults.frame();
  assert.equal(defaults.requests.length,1);assert.ok(defaults.delays.includes(100));
  const timing=harness(2,{camera_concurrency:2,camera_scan_interval:0.25});await timing.get('startSignCamera()');timing.frame();
  assert.equal(timing.requests.length,2);assert.ok(timing.delays.includes(250));
  console.log('camera concurrency contract passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
