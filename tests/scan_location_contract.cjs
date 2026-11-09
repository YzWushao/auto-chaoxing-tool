const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
async function check(capability,source,ack=true){
 const elements={},requests=[];let supported=true,fixes=0;
 const el=id=>elements[id]??={dataset:{ready:'true'},disabled:false,checked:false,textContent:'',innerHTML:'',pause(){},play:async()=>{},readyState:0,classList:{remove(){}}};
 el('server-camera-report-location').checked=true;
 el('server-camera-use-device-location').checked=source==='device';
 const ctx=vm.createContext({console,Promise,AbortController,JSON,Map,Set,Date,
  window:{isSecureContext:true,addEventListener(){},DevicePosition:{available:()=>supported,get:async()=>{fixes++;return {latitude:31.2,longitude:121.4,accuracy:10,captured_at:123};}}},
  state:{csrf:'test'},QRVision:{constraints:()=>({}),focus:async()=>{},outline(){}},
  document:{hidden:false,getElementById:el,addEventListener(){},querySelector:s=>s.includes('server-camera-location')&&source==='preset'?{value:capability?'opaque-point':'["学校","教学楼"]'}:null,
   querySelectorAll:s=>s.includes('server-camera-user')&&s.includes(':checked')?[{value:'selected-user'}]:[],createElement:()=>({getContext:()=>({})})},
  navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}],getVideoTracks:()=>[{addEventListener(){}}]})}},
  setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},
  fetch:async(path,options)=>{requests.push({path,body:JSON.parse(options.body)});return {ok:true,json:async()=>({id:'test-run',state:'running',message:'test',location_mode:ack?source:'none',accounts:[]})};}
 });
 vm.runInContext(fs.readFileSync('web/server-camera.js','utf8'),ctx);
 vm.runInContext(`serverCamera.capability=${capability};serverCamera.pickUsers=${capability};serverCamera.csrf='test';const baseRender=renderServerCameraState;`,ctx);
 ctx.dropCapability=()=>{supported=false;};
 vm.runInContext('renderServerCameraState=(...args)=>{baseRender(...args);dropCapability();}',ctx);
 await vm.runInContext('startServerCamera()',ctx);
 const start=requests.find(x=>x.path.endsWith('/start')||x.path==='/api/camera-stream');
 assert(start);assert.equal(start.body.report_location,true);
 if(source==='device'){assert.equal(fixes,1);assert.equal(start.body.device_location.latitude,31.2);}
 else assert.deepEqual(start.body.location,capability?'opaque-point':{school:'学校',name:'教学楼'});
 if(ack){assert.equal(vm.runInContext('serverCamera.phase',ctx),'running');assert.match(el('server-camera-counter').textContent,/已绑定/);}
 else{assert.notEqual(vm.runInContext('serverCamera.phase',ctx),'running');assert.match(el('server-camera-status').textContent,/未确认位置/);assert(requests.some(x=>x.path.endsWith('/stop')||x.path.endsWith('/close')));}
 vm.runInContext('stopServerCamera()',ctx);
}
(async()=>{for(const capability of [false,true])for(const source of ['preset','device'])for(const ack of [true,false])await check(capability,source,ack);console.log('JPEG location intent survives capability changes; admin/QQ preset/device paths require server acknowledgement');})().catch(e=>{console.error(e);process.exitCode=1;});
