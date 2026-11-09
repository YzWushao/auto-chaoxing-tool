const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const elements={},events={},requests=[];let callbacks,stops=0,completed=false;
const element=id=>elements[id]??={disabled:false,textContent:'',innerHTML:'',dataset:{},pause(){}};
const context=vm.createContext({console,Promise,AbortController,JSON,Date,Map,Set,
  QRVision:{outline(){}},state:{csrf:'offline',preferences:{camera_scan_interval:.3}},
  window:{addEventListener(){},AndroidScanner:{start:async value=>{callbacks=value;},stop:()=>stops++}},
  document:{hidden:false,getElementById:element,querySelector:()=>null,
    querySelectorAll:selector=>selector.includes(':checked')?[{value:'offline-account'}]:[],addEventListener:(name,fn)=>events[name]=fn},
  navigator:{mediaDevices:{getUserMedia(){throw Error('Native scanning must not request a browser camera');}}},
  setInterval:()=>1,clearInterval(){},setTimeout:()=>1,clearTimeout(){},
  fetch:async(path,options)=>{
    requests.push({path,...options});
    const body=options.body?JSON.parse(options.body):{};
    const data={id:'native-run',input:'native',message:'offline',terminal:completed,state:completed?'completed':'running',accounts:[],location_mode:body.device_location?'device':body.location?'preset':'none'};
    return {ok:true,status:200,json:async()=>data};
  }});
vm.runInContext(fs.readFileSync('web/server-camera.js','utf8'),context);
(async()=>{
  assert.equal(requests.length,0);
  await vm.runInContext('startServerCamera()',context);
  assert.equal(callbacks.interval,300);
  assert.deepEqual(JSON.parse(requests[0].body),{account_ids:['offline-account'],input:'native'});
  await callbacks.onScan('https://offline.invalid/?id=902&enc=offline');
  assert.equal(requests[1].path,'/api/camera-stream/native-run/qr');
  assert.equal(JSON.parse(requests[1].body).qr,'https://offline.invalid/?id=902&enc=offline');
  assert.ok(requests.every(r=>!r.path.endsWith('/frame')));
  completed=true;await vm.runInContext('viewServerCameraResult()',context);
  assert.equal(stops,1);const count=requests.length;
  await callbacks.onScan('late');assert.equal(requests.length,count);
  completed=false;
  context.window.AndroidScanner.deviceLocationAvailable=true;
  context.window.AndroidScanner.getDeviceLocation=async()=>({latitude:31.2,longitude:121.4,accuracy:12,captured_at:123});
  element('server-camera-report-location').checked=true;element('server-camera-use-device-location').checked=true;
  await vm.runInContext('startServerCamera()',context);
  const deviceRequest=JSON.parse(requests[count].body);
  assert.equal(deviceRequest.input,'native');assert.equal(deviceRequest.device_location.accuracy,12);
  assert.equal(deviceRequest.report_location,true);
  assert.equal(deviceRequest.location,undefined);
  vm.runInContext("renderServerCameraState({accounts:[{name:'offline',state:'pending',retry_code:'location_rejected',message:'retry',attempts:1,failures:1}]})",context);
  assert.ok(element('server-camera-results').innerHTML.includes('上报失败'));
  vm.runInContext('stopServerCamera()',context);
  // A capability refresh during the start render must not turn a checked position into an unlocated request.
  context.window.DevicePosition={available:()=>true,get:async()=>({latitude:31.2,longitude:121.4,accuracy:12,captured_at:123})};
  context.window.AndroidScanner.deviceLocationAvailable=false;
  vm.runInContext('const originalRenderForTest=renderServerCameraState;renderServerCameraState=(...args)=>{originalRenderForTest(...args);window.DevicePosition.available=()=>false;}',context);
  const beforeRace=requests.length;
  await vm.runInContext('startServerCamera()',context);
  const raced=JSON.parse(requests[beforeRace].body);
  assert.equal(raced.report_location,true);assert.equal(raced.device_location.latitude,31.2);
  vm.runInContext('stopServerCamera()',context);
  console.log('Native scanner starts explicitly, only sends QR results, stops after completion');
})().catch(error=>{console.error(error);process.exitCode=1;});
