const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const elements={},events={},requests=[],pending=[],tracks=[],choices=[];
let locationSelection=null;
const el=id=>elements[id]??={disabled:false,hidden:true,textContent:'',innerHTML:'',dataset:{},readyState:4,videoWidth:640,videoHeight:480,
  play:async()=>{},pause(){},setAttribute(){},removeAttribute(){},querySelector:()=>({setAttribute(){}})};
const blob={size:900,type:'image/jpeg'};
const ctx=vm.createContext({console,Promise,AbortController,JSON,Map,Set,Date,QRVision:require('../web/qr-vision.js'),performance:{now:()=>1000},
  location:{hash:'#'+'a'.repeat(43),pathname:'/scan'},history:{replaceState(){ctx.location.hash='';}},
  window:{isSecureContext:true,addEventListener:(n,f)=>events[n]=f},
  document:{hidden:false,getElementById:el,querySelector:s=>s.includes('server-camera-location')?locationSelection:{},querySelectorAll:s=>s.includes(':checked')?choices.filter(a=>a.checked):choices,
    addEventListener:(n,f)=>events['document:'+n]=f,createElement:()=>({getContext:()=>({drawImage(){}}),toBlob:fn=>fn(blob)})},
  navigator:{mediaDevices:{getUserMedia:async()=>{const track={stop(){this.stopped=true},addEventListener(){}};tracks.push(track);return {getTracks:()=>[track],getVideoTracks:()=>[track]};}}},
  setInterval:()=>1,clearInterval(){},setTimeout:()=>1,clearTimeout(){},
  fetch:(path,options)=>{assert(path.startsWith('/scan-api/'));requests.push({path,...options});return new Promise(resolve=>pending.push(resolve));}
});
const run=code=>vm.runInContext(code,ctx),respond=(i,data,status=200)=>pending[i]({ok:status<400,status,json:async()=>data});
run(fs.readFileSync('web/server-camera.js','utf8'));
(async()=>{
 respond(0,{csrf:'test-csrf',select_users:true,remaining_seconds:300,concurrency:5,accounts:[
  {id:'opaque-a',name:'测试甲',status:'active'},{id:'opaque-b',name:'测试乙',status:'active'}]});await flush();
 assert.equal(el('server-camera-user-panel').hidden,false);assert.match(el('server-camera-user-list').innerHTML,/测试甲/);
 assert.equal(el('server-camera-start').disabled,true);await run('startServerCamera()');assert.equal(tracks.length,0);
 choices.push({value:'opaque-a',checked:false,dataset:{}},{value:'opaque-b',checked:false,dataset:{}},
  {value:'expired-user',checked:false,disabled:true,dataset:{unavailable:'true'}});
 run('selectAllServerCameraUsers()');assert.equal(choices[0].checked,true);assert.equal(choices[1].checked,true);
 assert.equal(choices[2].checked,false,'Expired users must not be selected');assert.equal(requests.length,1,'Select-all must not sign or start a camera');
 choices[0].checked=false;choices[1].checked=false;
 const all=el('server-camera-select-all');all.id='server-camera-select-all';all.checked=true;
 events['document:change']({target:all});assert.equal(el('server-camera-user-list').hidden,true);assert.equal(choices[0].checked,true);
 all.checked=false;events['document:change']({target:all});assert.equal(el('server-camera-user-list').hidden,false);assert.equal(choices[0].checked,false);
 choices[1].checked=true;
 const report=el('server-camera-report-location');report.id='server-camera-report-location';report.checked=true;
 events['document:change']({target:report});assert.equal(el('server-camera-location-list').hidden,false);
 assert.throws(()=>run('selectedServerCameraLocation()'),/选择一个点位/);
 locationSelection={value:'opaque-location'};assert.equal(run('selectedServerCameraLocation()'),'opaque-location');
 report.checked=false;events['document:change']({target:report});assert.equal(el('server-camera-location-list').hidden,true);
 assert.equal(run('selectedServerCameraLocation()'),null,'Hidden location must not be sent');
 events['document:change']({target:{name:'server-camera-user'}});assert.equal(el('server-camera-start').disabled,false);
 const starting=run('startServerCamera()');await flush();
 assert.equal(tracks.length,1);assert.deepEqual(JSON.parse(requests[1].body),{account_ids:['opaque-b']});
 assert(choices.every(a=>a.disabled));
 run('selectAllServerCameraUsers()');assert.equal(choices[0].checked,false,'Selection freezes while starting');
 respond(1,{id:'run-test',state:'running',terminal:false,accounts:[],message:'等待',frames:0});await starting;await flush();
 assert.equal(requests[2].path,'/scan-api/frame');assert.equal(requests[2].body,blob);
 respond(2,{id:'run-test',terminal:true,state:'completed',accounts:[{id:'opaque-b',name:'测试乙',state:'succeeded',attempts:1,failures:0,message:'成功'}],message:'完成'});await flush();
 assert.equal(tracks[0].stopped,true);assert.equal(el('server-camera-start').disabled,true);
 assert.match(el('server-camera-results').innerHTML,/测试乙/);assert(!el('server-camera-results').innerHTML.includes('测试甲'));
 assert(choices.every(a=>a.disabled));assert.equal(requests.length,3);
 console.log('Manual scoped user selection, JPEG path and result lifecycle verified');
})().catch(e=>{console.error(e);process.exitCode=1;});
