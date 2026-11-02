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
    const data={id:'native-run',input:'native',message:'offline',terminal:completed,state:completed?'completed':'running',accounts:[]};
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
  console.log('Native scanner starts explicitly, only sends QR results, stops after completion');
})().catch(error=>{console.error(error);process.exitCode=1;});
