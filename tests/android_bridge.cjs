const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const messages=[],events={};let stopped=false;
const bridge={postMessage:raw=>messages.push(JSON.parse(raw))};
const context=vm.createContext({console,JSON,String,Math,Error,Promise,
  window:{AutoChaoxingNative:bridge,addEventListener:(name,fn)=>events[name]=fn},
  location:{hash:'#study'},document:{documentElement:{classList:{add(){}}},
    getElementById:id=>id==='app-screen'?{classList:{contains:()=>false}}:null,addEventListener:(name,fn)=>events[name]=fn},
  setTimeout:()=>1,clearTimeout(){},setInterval:()=>1});
vm.runInContext(fs.readFileSync('web/android-client.js','utf8'),context);
(async()=>{
  assert.equal(messages.length,0,'Loading a page never starts a camera');
  events.DOMContentLoaded();assert.equal(messages[0].type,'layout');assert.equal(messages[0].route,'study');
  const scanner=context.window.AndroidScanner,results=[];
  const ready=scanner.start({interval:50,onScan:qr=>results.push(qr),onClosed:()=>stopped=true});
  const id=messages[1].id;assert.equal(messages[1].interval,100);
  bridge.onmessage({data:JSON.stringify({type:'qr',id:'old',qr:'stale'})});assert.equal(results.length,0);
  bridge.onmessage({data:JSON.stringify({type:'started',id})});await ready;
  bridge.onmessage({data:JSON.stringify({type:'qr',id,qr:'offline-code'})});assert.deepEqual(results,['offline-code']);
  scanner.configureInterval(800);assert.equal(messages[2].type,'interval');assert.equal(messages[2].interval,800);
  scanner.stop();assert.equal(messages[3].type,'stop');
  bridge.onmessage({data:JSON.stringify({type:'qr',id,qr:'late'})});assert.equal(results.length,1);
  assert.equal(stopped,false);
  assert.equal(scanner.deviceLocationAvailable,false);
  const capability=scanner.waitForDeviceLocation();assert.equal(messages.at(-1).type,'capabilities');
  bridge.onmessage({data:JSON.stringify({type:'capabilities',device_location:true})});
  assert.equal(await capability,true);
  assert.equal(scanner.deviceLocationAvailable,true);
  const locating=scanner.getDeviceLocation();await new Promise(resolve=>setImmediate(resolve));const request=messages.at(-1);
  assert.equal(request.type,'device_location');
  bridge.onmessage({data:JSON.stringify({type:'device_location',id:'stale',location:{latitude:0}})});
  bridge.onmessage({data:JSON.stringify({type:'device_location',id:request.id,location:{latitude:1,longitude:2,accuracy:5,captured_at:123}})});
  assert.equal((await locating).accuracy,5);
  const canceled=scanner.getDeviceLocation();await new Promise(resolve=>setImmediate(resolve));scanner.cancelLocation();
  await assert.rejects(canceled,/取消/);assert.equal(messages.at(-1).type,'cancel_location');
  const count=messages.length,early=scanner.getDeviceLocation();scanner.cancelLocation();
  await assert.rejects(early,/取消/);assert.equal(messages.length,count,'Cancellation while waiting must prevent a late native position request');
  console.log('Origin-scoped native bridge handshake, stale callback isolation and explicit start/stop verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
