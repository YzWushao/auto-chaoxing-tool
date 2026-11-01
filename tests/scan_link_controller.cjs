/* Synthetic browser lifecycle; no camera hardware or platform calls. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const qr='https://mobilelearn.chaoxing.com/?id=902&enc=OFFLINE_SCAN_TOKEN_123';
function harness(){
  let now=1000;
  const elements={},events={},requests=[],pending=[],workers=[],tracks=[],stored=new Map();
  const element=id=>elements[id]??=( {disabled:false,textContent:'',readyState:4,videoWidth:640,videoHeight:480,
    play:async()=>{},pause(){},addEventListener:(name,fn)=>events[id+':'+name]=fn});
  const context=vm.createContext({console,Promise,Uint8ClampedArray,AbortController,
    SignCameraQueue:require('../web/camera-queue.js'),
    Date:class extends Date{static now(){return now;}},performance:{now:()=>now},
    location:{hash:'#'+'a'.repeat(43),pathname:'/scan'},
    history:{replaceState(){context.location.hash='';}},
    sessionStorage:{getItem:key=>stored.get(key),setItem:(key,value)=>stored.set(key,value),removeItem:key=>stored.delete(key)},
    window:{isSecureContext:true,addEventListener:(name,fn)=>events['window:'+name]=fn},
    navigator:{mediaDevices:{getUserMedia:async()=>{
      const track={stops:0,stop(){this.stops++;},addEventListener(){}};tracks.push(track);
      return {getTracks:()=>[track],getVideoTracks:()=>[track]};
    }}},
    document:{hidden:false,getElementById:element,addEventListener:(name,fn)=>events[name]=fn,
      createElement:()=>({getContext:()=>({drawImage(){},getImageData:()=>({data:new Uint8ClampedArray(64)})})})},
    Worker:class{constructor(){workers.push(this);}postMessage(){}terminate(){this.terminated=true;}},
    setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},
    fetch:(path,options)=>{
      assert.equal(context.location.hash,'','Erase the raw link before fetching');
      assert.ok(path.startsWith('/scan-api/'),'No administrator API is allowed');
      requests.push({path,...options});
      return new Promise((resolve,reject)=>pending.push({resolve,reject}));
    }
  });
  const run=code=>vm.runInContext(code,context);
  vm.runInContext(fs.readFileSync('web/scan-link.js','utf8'),context);
  function respond(index,status,data){pending[index].resolve({ok:status<400,status,json:async()=>data});}
  const frame=(text,age=0)=>{run(`scan.frameAt=${now-age}`);workers.at(-1).onmessage({data:{text}});};
  return {context,run,respond,frame,events,requests,pending,workers,tracks,element,advance:value=>now+=value};
}
(async()=>{
  const h=harness();
  assert.equal(h.tracks.length,0,'No camera before capability is claimed');
  assert.equal(JSON.parse(h.requests[0].body).token.length,43);
  h.respond(0,200,{csrf:'test-csrf',remaining_seconds:300,scan_interval:.1});await flush();
  assert.equal(h.tracks.length,1);assert.equal(h.run('scan.running'),true);assert.equal(h.run('scan.interval'),100);
  h.frame(qr,2000);assert.equal(h.requests.length,1,'Stale frames cannot submit');
  h.frame(qr);assert.equal(h.requests.length,2);assert.deepEqual(JSON.parse(h.requests[1].body),{qr});
  assert.equal(h.requests[1].headers['X-Scan-CSRF'],'test-csrf');
  h.frame(qr);assert.equal(h.requests.length,2,'Never overlap sign requests');
  h.respond(1,502,{error:'过期'});await flush();
  h.frame(qr);assert.equal(h.requests.length,2,'Throttle failed requests');
  h.advance(3000);h.frame(qr);assert.equal(h.requests.length,3);
  h.respond(2,200,{completed:true,message:'本次签到已完成，入口已失效。'});await flush();
  assert.equal(h.run('scan.valid'),false);assert.equal(h.tracks[0].stops,1);assert.equal(h.workers[0].terminated,true);
  h.frame(qr);assert.equal(h.requests.length,3);assert.equal(h.element('start').disabled,true);

  const hidden=harness();hidden.respond(0,200,{csrf:'csrf',remaining_seconds:300,scan_interval:.25});await flush();
  hidden.context.document.hidden=true;hidden.events.visibilitychange();
  assert.equal(hidden.tracks[0].stops,1);assert.equal(hidden.run('scan.valid'),true);
  assert.equal(hidden.run('scan.interval'),250);
  hidden.events['window:pagehide']();assert.equal(hidden.run('scan.valid'),false);
  assert.equal(hidden.requests.at(-1).path,'/scan-api/close');assert.equal(hidden.requests.at(-1).keepalive,true);

  const expired=harness();expired.respond(0,200,{csrf:'csrf',remaining_seconds:1,scan_interval:.1});await flush();
  expired.advance(1100);expired.run('tick()');
  assert.equal(expired.run('scan.valid'),false);assert.equal(expired.tracks[0].stops,1);
  assert.match(expired.element('status').textContent,/超时/);

  const late=harness();let allow;
  late.context.navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>allow=resolve);
  late.respond(0,200,{csrf:'csrf',remaining_seconds:300,scan_interval:.1});await flush();
  late.events['close:click']();let stops=0;
  allow({getTracks:()=>[{stop(){stops++;}}]});await flush();
  assert.equal(stops,1,'Late camera permissions must release hardware after close');
  assert.equal(late.run('scan.running'),false);

  const blocked=harness();blocked.respond(0,410,{error:'已失效'});await flush();
  assert.equal(blocked.tracks.length,0);assert.equal(blocked.run('scan.valid'),false);
  console.log('one-time scan controller lifecycle verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
