/* Phone produces JPEG and displays opaque status; it never decodes or signs. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const elements={},events={},requests=[],pending=[],tracks=[];
const element=id=>elements[id]??={disabled:false,textContent:'',innerHTML:'',dataset:{},readyState:4,videoWidth:640,videoHeight:480,
  play:async()=>{},pause(){},setAttribute(){},removeAttribute(){},querySelector:()=>({setAttribute(){}})};
const blob={size:1200,type:'image/jpeg'};
const context=vm.createContext({console,Promise,AbortController,JSON,Map,Set,Date,
  QRVision:require('../web/qr-vision.js'),performance:{now:()=>1000},
  location:{hash:'#'+'a'.repeat(43),pathname:'/scan'},history:{replaceState(){context.location.hash='';}},
  window:{isSecureContext:true,addEventListener:(n,fn)=>events[n]=fn},
  document:{hidden:false,getElementById:element,querySelector:()=>({}),querySelectorAll:()=>[],
    addEventListener:(n,fn)=>events['document:'+n]=fn,
    createElement:()=>({getContext:()=>({drawImage(){}}),toBlob:fn=>fn(blob)})},
  navigator:{mediaDevices:{getUserMedia:async()=>{
    const track={stops:0,stop(){this.stops++;},addEventListener(){}};tracks.push(track);
    return {getTracks:()=>[track],getVideoTracks:()=>[track]};
  }}},
  setInterval:()=>1,clearInterval(){},setTimeout:()=>1,clearTimeout(){},
  fetch:(path,options)=>{
    assert.equal(context.location.hash,'');
    assert.ok(path.startsWith('/scan-api/'));assert.ok(!path.includes('submit'));
    requests.push({path,...options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));
  }
});
vm.runInContext(fs.readFileSync('web/server-camera.js','utf8'),context);
const run=code=>vm.runInContext(code,context);
const respond=(i,data,status=200)=>pending[i].resolve({ok:status<400,status,json:async()=>data});
(async()=>{
  assert.equal(tracks.length,0,'No automatic camera use');
  assert.equal(requests.length,0,'Fixed page must not claim credentials from its URL');
  const verifying=run('verifyServerScanCode("12345678")');await flush();
  assert.equal(requests[0].path,'/scan-api/verify');assert.deepEqual(JSON.parse(requests[0].body),{code:'12345678'});
  respond(0,{csrf:'offline-csrf',remaining_seconds:300});await verifying;await flush();
  assert.equal(element('server-camera-start').disabled,false);
  const starting=run('startServerCamera()');await flush();
  assert.equal(tracks.length,1);assert.equal(requests[1].path,'/scan-api/start');
  assert.deepEqual(JSON.parse(requests[1].body),{});
  respond(1,{id:'offline-run',state:'running',terminal:false,accounts:[],message:'waiting',frames:0});await starting;await flush();
  assert.equal(requests[2].path,'/scan-api/frame');assert.equal(requests[2].body,blob);
  assert.equal(requests[2].headers['Content-Type'],'image/jpeg');
  assert.equal(requests[2].headers['X-Scan-CSRF'],'offline-csrf');
  respond(2,{id:'offline-run',state:'running',terminal:false,accounts:[],message:'server scanning',frames:1});await flush();
  const viewing=run('viewServerCameraResult()');await flush();
  assert.equal(requests[3].path,'/scan-api/status');
  respond(3,{id:'offline-run',state:'completed',terminal:true,message:'全部成功',frames:1,decoded_frames:1,
    accounts:[{id:'0',name:'当前用户',state:'succeeded',attempts:1,failures:0,message:'成功'}]});await viewing;
  assert.equal(tracks[0].stops,1);assert.equal(run('serverCamera.phase'),'ended');
  assert.equal(element('server-camera-start').disabled,true);assert.match(element('server-camera-results').innerHTML,/成功/);
  assert.equal(requests.length,4,'Completion must not start another upload or signing request');
  console.log('push-only phone camera controls and results verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
