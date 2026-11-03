const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const QRVision=require('../web/qr-vision.js');
const calls=[],video={videoWidth:1920,videoHeight:1080,readyState:4},canvas={width:0,height:0,toBlob:fn=>fn({size:123})},context={drawImage:(...args)=>calls.push(args)};
(async()=>{
 await QRVision.jpeg(video,canvas,context,2);
 assert.deepEqual(calls.at(-1).slice(1),[480,270,960,540,0,0,1920,1080]);
 QRVision.draw(video,canvas,context,2,1280);
 assert.deepEqual(calls.at(-1).slice(1),[480,270,960,540,0,0,1280,720]);
 await QRVision.jpeg(video,canvas,context,1);assert.deepEqual(calls.at(-1).slice(1),[0,0,1920,1080,0,0,1920,1080]);
 await QRVision.jpeg(video,canvas,context,99);assert.equal(calls.at(-1)[3],384);
 const elements={},events={},frames=new Map(),classes=new Set();let frameId=0;
 const element=id=>elements[id]??={value:'',textContent:'',hidden:false,dataset:{},pause(){},setAttribute(){},removeAttribute(){},querySelector:()=>null};
 Object.assign(element('server-camera-video'),video,{classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name),remove:name=>classes.delete(name)}});
 Object.assign(element('server-camera-zoom-preview'),{getContext:()=>context});element('server-camera-zoom').value='2';
 const ctx=vm.createContext({QRVision,console,Map,Set,JSON,Date,AbortController,
  window:{addEventListener(){}},document:{getElementById:element,querySelector:()=>null,querySelectorAll:()=>[],addEventListener:(name,fn)=>events[name]=fn},
  requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id),
  setTimeout,clearTimeout,clearInterval,setInterval});
 vm.runInContext(fs.readFileSync('web/server-camera.js','utf8'),ctx);
 const run=source=>vm.runInContext(source,ctx);
 const html=run('serverCameraControls()');assert(html.indexOf('id="server-camera-zoom"')>html.indexOf('id="server-camera-video"'));
 events.input({target:{id:'server-camera-zoom'}});assert.equal(element('server-camera-zoom-value').textContent,'2.0×');
 run("serverCamera.phase='running';startServerCameraZoomPreview(serverCamera.generation)");
 const tick=at=>{const [id,fn]=frames.entries().next().value;frames.delete(id);fn(at);};
 tick(100);assert.equal(element('server-camera-zoom-preview').hidden,false);assert(classes.has('camera-digital-zoom'));
 assert.equal(calls.at(-1)[3],960);
 element('server-camera-zoom').value='1';tick(200);assert.equal(element('server-camera-zoom-preview').hidden,true);assert(!classes.has('camera-digital-zoom'));
 run('scRelease()');assert.equal(frames.size,0);assert.equal(element('server-camera-zoom-preview').hidden,true);
 console.log('Zoom crop matches preview/JPEG; live slider, 1x reset and release verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
