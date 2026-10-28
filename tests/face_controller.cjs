/* Synthetic camera/HTTP contract test. No camera device or personal photos. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),requests=[],tracks=[],events={};let submitCount=0,permissions=0,allow=null,uploadReply=null;
function el(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',dataset:{},style:{},checked:false,open:false,isConnected:true,
  classList:{add(){},remove(){},toggle(){}},pause(){},play:async()=>{},showModal(){this.open=true;},close(){this.open=false;},removeAttribute(){},
  append(){},addEventListener(){},requestSubmit(){submitCount++;}});return elements.get(id);}
function stream(){const track={stops:0,stop(){this.stops++;}};tracks.push(track);return{getTracks:()=>[track]};}
const context=vm.createContext({URL,Promise,console,AbortController,setTimeout,clearTimeout,
  state:{authenticated:true,accounts:[{id:'a',name:'甲'},{id:'b',name:'乙'}]},
  cameraSession:{queue:{activityId:'902',current:{id:'b'}},facePaused:true},
  window:{isSecureContext:true,addEventListener:(name,fn)=>events['window:'+name]=fn},
  navigator:{mediaDevices:{getUserMedia:()=>{permissions++;return new Promise(resolve=>allow=resolve);}}},
  document:{hidden:false,addEventListener:(name,fn)=>events[name]=fn,createElement:tag=>tag==='canvas'?{
    getContext:()=>({fillRect(){},drawImage(){}}),toDataURL:()=> 'data:image/jpeg;base64,AAAA'
  }:{}},
  $:selector=>el(selector),esc:value=>String(value),button:()=>'',toast:()=>{},suspendCameraForFace:()=>{},renderCameraStatus:()=>{},
  api:(path,method,body)=>{
    requests.push({path,method,body});
    if(path.endsWith('/face'))return new Promise(resolve=>uploadReply=resolve);
    if(path.includes('/requirements'))return Promise.resolve({requirements:{official_url:'https://mobilelearn.chaoxing.com/newsign/preSign'}});
    return Promise.resolve({cancelled:true});
  }
});
vm.runInContext(fs.readFileSync('web/sign-face.js','utf8'),context);
const get=code=>vm.runInContext(code,context),flush=async()=>{await Promise.resolve();await Promise.resolve();};
(async()=>{
  get("showSignFace('sign','a','901','course')");assert.equal(permissions,0);
  const opening=get('startFaceCamera()');get('closeSignFace()');const late=stream();allow(late);await opening;
  assert.equal(tracks.at(-1).stops,1,'A permission grant after closing must release its stream');
  get("showSignFace('sign','a','901','course')");const active=get('startFaceCamera()');allow(stream());await active;
  get('prepareFacePhoto({},640,480)');assert.equal(tracks.at(-1).stops,1);
  assert.equal(requests.filter(r=>r.path.endsWith('/face')).length,0,'Taking a photo must not upload it');
  await get('uploadFacePhoto()');assert.equal(requests.filter(r=>r.path.endsWith('/face')).length,0,'Consent is required');
  el('#face-consent').checked=true;const cancelled=get('uploadFacePhoto()');get('closeSignFace()');uploadReply({face_id:'cancelled-proof'});await cancelled;
  assert.ok(requests.some(r=>r.path.endsWith('/face/cancelled-proof/cancel')));assert.equal(submitCount,0);
  get("showSignFace('sign','a','901','course')");get('prepareFacePhoto({},640,480)');el('#face-consent').checked=true;
  el('#modal').open=true;el('#sign-form').dataset={account:'a',activity:'901'};
  const accepted=get('uploadFacePhoto()');uploadReply({face_id:'photo-for-a'});await accepted;
  assert.equal(submitCount,1);assert.equal(el('#sign-form').dataset.face,'photo-for-a');assert.equal(get('faceCapture.image'),'');
  get("showSignFace('camera','b','902','group')");get('prepareFacePhoto({},640,480)');el('#face-consent').checked=true;
  const second=get('uploadFacePhoto()');uploadReply({face_id:'photo-for-b'});await second;
  assert.equal(get('cameraSession.faceProof.account'),'b');assert.equal(get('cameraSession.faceProof.id'),'photo-for-b');
  assert.equal(submitCount,1,'Queue photo preparation must not submit a different manual form');
  get("showSignFace('sign','a','901','course')");const hidden=get('startFaceCamera()');context.document.hidden=true;events.visibilitychange();allow(stream());await hidden;
  assert.equal(tracks.at(-1).stops,1);assert.equal(get('faceCapture.target'),null);
  await flush();console.log('face capture contract passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
