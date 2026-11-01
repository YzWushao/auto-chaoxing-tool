/* A capability-only page: it never calls the administrator API. */
'use strict';
const scan={csrf:'',valid:false,running:false,starting:false,busy:false,stream:null,worker:null,
  timer:null,decodeTimer:null,poll:null,clock:null,decoding:false,generation:0,deadline:0,interval:100,retryAt:0,frameAt:0};
const el=id=>document.getElementById(id),storageKey='ac-scan-csrf';
function remember(value){try{if(value)sessionStorage.setItem(storageKey,value);else sessionStorage.removeItem(storageKey);}catch{}}
function recalled(){try{return sessionStorage.getItem(storageKey)||'';}catch{return '';}}
function message(text){el('status').textContent=text;}
async function scanRequest(path,body){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),25000);
  try{
    const response=await fetch('/scan-api/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
      headers:{'Content-Type':'application/json','X-Scan-Request':'1','X-Scan-CSRF':scan.csrf},
      body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
    const data=await response.json();
    if(!response.ok)throw Object.assign(new Error(data.error||'请求未确认'),{status:response.status,code:data.code});
    return data;
  }finally{clearTimeout(timeout);}
}
function releaseCamera(){
  scan.generation++;scan.running=false;scan.starting=false;scan.decoding=false;
  clearTimeout(scan.timer);clearTimeout(scan.decodeTimer);scan.worker?.terminate();scan.worker=null;
  scan.stream?.getTracks().forEach(track=>track.stop());scan.stream=null;
  const video=el('video');video.pause();video.srcObject=null;
  el('start').disabled=!scan.valid||scan.busy;
}
function finish(text){
  scan.valid=false;releaseCamera();clearInterval(scan.clock);clearInterval(scan.poll);remember('');
  el('start').disabled=true;el('close').disabled=true;el('remaining').textContent='入口已关闭';message(text);
}
function closeRemote(){
  if(!scan.csrf)return;
  void fetch('/scan-api/close',{method:'POST',credentials:'same-origin',keepalive:true,
    headers:{'Content-Type':'application/json','X-Scan-Request':'1','X-Scan-CSRF':scan.csrf},body:'{}'}).catch(()=>{});
}
function tick(){
  const seconds=Math.max(0,Math.ceil((scan.deadline-performance.now())/1000));
  el('remaining').textContent=`剩余 ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
  if(!seconds){closeRemote();finish('等待已超时，入口已失效，请回 QQ 重新获取。');}
}
async function submitQR(raw,frameAt,generation){
  if(!scan.valid||!scan.running||scan.busy||generation!==scan.generation||Date.now()-frameAt>1500||Date.now()<scan.retryAt)return;
  if(!SignCameraQueue.parameters(raw))return;
  scan.busy=true;scan.retryAt=Date.now()+2500;message('已识别二维码，正在提交本次签到…');
  try{
    const result=await scanRequest('submit',{qr:raw});
    if(result.completed)finish(result.message);
    else{closeRemote();finish('请求结果未确认，请先核对官方签到结果。');}
  }catch(error){
    if(error.status===410){finish(error.message);}
    else if(error.code==='stop'||!error.status){releaseCamera();message(error.message||'连接异常，请先核对官方结果。');}
    else message(error.message);
  }finally{scan.busy=false;el('start').disabled=!scan.valid||scan.running;}
}
async function startCamera(){
  if(!scan.valid||scan.running||scan.starting||scan.busy)return;
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){message('当前浏览器无法使用摄像头。请通过 HTTPS 在系统浏览器中打开原始入口链接。');return;}
  scan.starting=true;el('start').disabled=true;const generation=++scan.generation;
  try{
    message('请允许本设备使用摄像头…');
    const stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:'environment'},width:{ideal:1280},height:{ideal:720}}});
    if(!scan.valid||generation!==scan.generation){stream.getTracks().forEach(track=>track.stop());return;}
    scan.stream=stream;const video=el('video');video.srcObject=stream;await video.play();
    if(!scan.valid||generation!==scan.generation)return;
    scan.starting=false;scan.running=true;
    stream.getVideoTracks().forEach(track=>track.addEventListener('ended',()=>{if(generation===scan.generation){releaseCamera();message('摄像头已断开，可重新开启。');}}));
    const canvas=document.createElement('canvas'),context=canvas.getContext('2d',{willReadFrequently:true});
    if(!context)throw new Error('canvas');
    const worker=new Worker('/static/sign-qr-worker.js?v=0.8.0');scan.worker=worker;
    worker.onerror=()=>{releaseCamera();message('识别组件未能启动，请重新开启摄像头。');};
    worker.onmessage=event=>{
      if(generation!==scan.generation||!scan.running)return;
      clearTimeout(scan.decodeTimer);scan.decoding=false;
      void submitQR(event.data?.text,scan.frameAt,generation);
    };
    const decode=()=>{
      if(!scan.running||generation!==scan.generation)return;
      scan.timer=setTimeout(decode,scan.interval);
      if(scan.decoding||video.readyState<2||!video.videoWidth)return;
      try{
        const scale=Math.min(1,1280/Math.max(video.videoWidth,video.videoHeight));
        canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale));
        context.drawImage(video,0,0,canvas.width,canvas.height);
        const pixels=context.getImageData(0,0,canvas.width,canvas.height).data;
        scan.frameAt=Date.now();scan.decoding=true;
        scan.decodeTimer=setTimeout(()=>{releaseCamera();message('识别超时，可重新开启摄像头。');},8000);
        worker.postMessage({pixels:pixels.buffer,width:canvas.width,height:canvas.height},[pixels.buffer]);
      }catch{releaseCamera();message('无法读取画面，可重新开启摄像头。');}
    };
    message('摄像头已开启，请持续对准本次签到二维码。');decode();
  }catch(error){
    if(generation!==scan.generation)return;
    releaseCamera();message(error.name==='NotAllowedError'?'摄像头权限尚未允许，请在浏览器中允许后点击“开启摄像头”。':'摄像头无法开启，请检查设备或使用系统浏览器。');
  }
}
async function initialize(){
  // Erase the capability from the address bar before any network request.
  const token=location.hash.slice(1);history.replaceState(null,'',location.pathname);
  try{
    scan.csrf=token?'':recalled();
    const data=await scanRequest(token?'claim':'session',token?{token}:undefined);
    scan.csrf=data.csrf||scan.csrf;remember(scan.csrf);scan.valid=true;
    scan.deadline=performance.now()+data.remaining_seconds*1000;scan.interval=Math.round(data.scan_interval*1000);
    el('close').disabled=false;el('start').disabled=false;tick();
    scan.clock=setInterval(tick,250);
    scan.poll=setInterval(async()=>{
      if(!scan.valid||scan.busy)return;
      try{await scanRequest('session');}catch(error){if(error.status===410)finish(error.message);}
    },5000);
    if(!document.hidden)await startCamera();else message('入口已领取，返回页面后点击“开启摄像头”。');
  }catch(error){finish(error.status?error.message:'无法连接，请回 QQ 重新获取入口并检查网络。');}
}
el('start').addEventListener('click',()=>void startCamera());
el('close').addEventListener('click',()=>{closeRemote();finish('本次扫码已结束，入口已失效。');});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&scan.valid){releaseCamera();message('页面已切到后台，摄像头已释放；返回后可重新开启。');}});
window.addEventListener('pagehide',()=>{if(scan.valid){closeRemote();finish('已离开扫码页面，入口已失效。');}});
void initialize();
