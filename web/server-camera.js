/* Phone is a JPEG producer + controls + results viewer. No QR payload handling. */
'use strict';
const serverCamera={generation:0,stream:null,runId:'',phase:'idle',busy:false,capability:false,csrf:'',
  timer:null,poll:null,expiry:null,abort:null,polling:false,pollGeneration:0,deadline:0,result:null,frameInterval:200,rowsKey:''};
const sc=id=>document.getElementById(id),scEsc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function serverCameraPage(){
  return heading('服务器扫码签到','手机仅上传连续 JPEG 画面；识别二维码、用户队列和签到提交均在服务器执行。','<a class="button secondary" href="#sign">返回签到中心</a>')+
    `<div id="server-camera-root"><div class="camera-layout"><section class="panel"><div class="panel-header"><h3>选择本次用户</h3><span class="badge purple">最多 ${state.preferences?.camera_concurrency??1} 人并发</span></div><div class="panel-body"><div class="camera-choice-list">${state.accounts.map(a=>`<label class="camera-choice"><input type="checkbox" name="server-camera-user" value="${scEsc(a.id)}"><span>${scEsc(a.name)}</span></label>`).join('')||'<p>请先添加超星用户。</p>'}</div><div class="field"><label for="server-camera-location">二维码附加位置</label><select id="server-camera-location"><option value="">不提交位置</option>${(state.location_presets||[]).flatMap(s=>s.points.map(p=>`<option value="${scEsc(JSON.stringify([s.school,p.name]))}">${scEsc(s.school+' · '+p.name)}</option>`)).join('')}</select></div><p class="setting-note">开始后画面发往当前项目服务器，在内存中识别，不录像、不保存图片。服务器只保留最新一帧，不排队积压。超星验证码继续使用现有自动验证流程；需要人工处理时会在结果中提示。</p><p class="setting-note">停止、离开页面或切后台会结束扫描；断流 10 秒后服务器自动停止。已发出的签到请求仍可能返回结果。</p></div></section><section class="panel"><div class="panel-header"><h3>连续扫码 · 服务器处理</h3></div><div class="panel-body">${serverCameraControls()}</div></section></div></div>`;
}
function serverCameraControls(){
  return '<div class="camera-preview server-camera-preview"><video id="server-camera-video" autoplay muted playsinline aria-label="本机摄像头预览"></video><svg id="server-camera-outline" class="qr-outline" preserveAspectRatio="xMidYMid meet" role="img" aria-label="服务器识别到的二维码位置" hidden><polygon vector-effect="non-scaling-stroke"></polygon></svg><p>开始后允许摄像头，将二维码放入画面。</p></div><div class="camera-control"><button type="button" class="button primary" id="server-camera-start">开始扫描</button><button type="button" class="button secondary" id="server-camera-stop" disabled>停止扫描</button><button type="button" class="button secondary" id="server-camera-result">查看结果</button></div><p id="server-camera-status" class="camera-status" role="status" aria-live="polite">点击开始扫描，画面将上传至本项目服务器。</p><p id="server-camera-counter" class="setting-note"></p><ol id="server-camera-results" class="camera-queue" aria-label="服务器签到结果"></ol>';
}
function scHeaders(jpeg=false){
  const headers={'Content-Type':jpeg?'image/jpeg':'application/json'};
  if(serverCamera.capability){headers['X-Scan-Request']='1';headers['X-Scan-CSRF']=serverCamera.csrf;}
  else headers['X-CSRF-Token']=state.csrf;
  return headers;
}
function scPath(action){
  const c=serverCamera;
  if(c.capability)return '/scan-api/'+({start:'start',frame:'frame',status:'status',stop:'close'}[action]);
  return '/api/camera-stream'+(action==='start'?'':`/${encodeURIComponent(c.runId)}`+(action==='status'?'':'/'+action));
}
async function scRequest(action,body,signal){
  const frame=action==='frame';
  const response=await fetch(scPath(action),{method:action==='status'?'GET':'POST',credentials:'same-origin',cache:'no-store',
    headers:scHeaders(frame),body:action==='status'?undefined:frame?body:JSON.stringify(body||{}),signal});
  let result;try{result=await response.json();}catch{throw new Error('服务器响应异常');}
  if(!response.ok)throw Object.assign(new Error(result.error||'请求失败'),{status:response.status});
  return result;
}
function scMessage(text){if(sc('server-camera-status'))sc('server-camera-status').textContent=text;}
function renderServerCameraState(data=serverCamera.result){
  if(!sc('server-camera-root'))return;
  const c=serverCamera,locked=c.phase==='running'||c.busy;
  sc('server-camera-start').disabled=locked||(c.capability&&c.phase==='ended');
  sc('server-camera-stop').disabled=!locked;
  document.querySelectorAll('[name="server-camera-user"],#server-camera-location').forEach(input=>input.disabled=locked);
  if(!data)return;
  scMessage(data.message);
  sc('server-camera-counter').textContent=`已接收 ${data.frames||0} 帧 · 已识别 ${data.decoded_frames||0} 帧`;
  const rowsKey=JSON.stringify(data.accounts||[]);
  if(c.rowsKey!==rowsKey){
    sc('server-camera-results').innerHTML=(data.accounts||[]).map(a=>`<li><div class="camera-row-head"><strong>${scEsc(a.name)}</strong><span class="badge ${a.state==='succeeded'?'green':'purple'}">${scEsc({succeeded:'签到成功',waiting:'需要处理',submitting:'正在签到',pending:'等待扫码'}[a.state]||a.state)}</span></div><p>${scEsc(a.message)} · 提交 ${a.attempts} 次 · 失败 ${a.failures} 次</p></li>`).join('');
    c.rowsKey=rowsKey;
  }
  QRVision.outline(sc('server-camera-outline'),c.phase==='running'?data.detection:null);
}
function scRelease(){
  const c=serverCamera;c.generation++;clearTimeout(c.timer);clearInterval(c.poll);c.abort?.abort();c.abort=null;
  c.stream?.getTracks().forEach(track=>track.stop());c.stream=null;c.busy=false;c.polling=false;
  const video=sc('server-camera-video');if(video){video.pause();video.srcObject=null;delete video.dataset.live;}
  QRVision.outline(sc('server-camera-outline'),null);
}
function stopServerCamera(message='',remote=true){
  const c=serverCamera,wasActive=c.phase==='running'||c.busy;
  if(remote&&wasActive&&c.runId){
    void fetch(scPath('stop'),{method:'POST',credentials:'same-origin',keepalive:true,headers:scHeaders(),body:'{}'}).catch(()=>{});
  }
  scRelease();c.phase=c.capability&&c.runId?'ended':'idle';
  if(c.capability&&c.runId){clearInterval(c.expiry);if(sc('remaining'))sc('remaining').textContent='本次扫描已结束';}
  renderServerCameraState();if(message)scMessage(message);
}
function scAccept(data,generation){
  if(generation!==serverCamera.generation)return;
  serverCamera.result=data;renderServerCameraState(data);
  if(data.terminal){stopServerCamera('',false);serverCamera.phase='ended';renderServerCameraState(data);}
}
async function viewServerCameraResult(){
  if(!serverCamera.runId){scMessage('尚未开始扫描。');return;}
  if(serverCamera.polling)return;
  const generation=serverCamera.generation;
  serverCamera.polling=true;serverCamera.pollGeneration=generation;
  const controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),8000);
  try{const result=await scRequest('status',undefined,controller.signal);scAccept(result,generation);}
  catch(error){scMessage(error.status===410?'本次入口已失效；已收到的结果仍显示在下方。':error.message);}
  finally{clearTimeout(deadline);if(serverCamera.pollGeneration===generation)serverCamera.polling=false;}
}
async function startServerCamera(){
  const c=serverCamera;if(c.phase==='running'||c.busy)return;
  const accounts=c.capability?[]:[...document.querySelectorAll('[name="server-camera-user"]:checked')].map(el=>el.value);
  if(!c.capability&&!accounts.length){scMessage('请先选择本次需要签到的用户。');return;}
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){scMessage('摄像头需要 HTTPS，请在系统浏览器中打开入口。');return;}
  c.busy=true;c.result=null;c.rowsKey='';c.runId='';const generation=++c.generation;renderServerCameraState();scMessage('请允许使用摄像头，开始后连续 JPEG 将上传到服务器。');
  try{
    const stream=await navigator.mediaDevices.getUserMedia(QRVision.constraints());
    if(generation!==c.generation){stream.getTracks().forEach(track=>track.stop());return;}
    c.stream=stream;const video=sc('server-camera-video');video.srcObject=stream;await video.play();
    if(generation!==c.generation)return;
    void QRVision.focus(stream.getVideoTracks()[0]);
    const payload={account_ids:accounts},location=sc('server-camera-location')?.value;
    if(location){const [school,name]=JSON.parse(location);payload.location={school,name};}
    const result=await scRequest('start',c.capability?{}:payload);
    if(generation!==c.generation){
      const path=c.capability?'/scan-api/close':`/api/camera-stream/${encodeURIComponent(result.id)}/stop`;
      void fetch(path,{method:'POST',credentials:'same-origin',headers:scHeaders(),body:'{}'}).catch(()=>{});return;
    }
    c.runId=result.id;c.frameInterval=Math.max(200,(result.frame_interval||.2)*1000);c.phase='running';c.busy=false;video.dataset.live='true';scAccept(result,generation);
    const canvas=document.createElement('canvas'),context=canvas.getContext('2d',{alpha:false});
    if(!context)throw new Error('当前浏览器无法读取摄像头画面');
    stream.getVideoTracks().forEach(track=>track.addEventListener('ended',()=>{if(generation===c.generation)stopServerCamera('摄像头断开，扫描已停止。');}));
    const upload=async()=>{
      if(generation!==c.generation||c.phase!=='running')return;
      try{
        if(video.readyState>=2&&video.videoWidth){
          const blob=await QRVision.jpeg(video,canvas,context);
          if(generation!==c.generation)return;
          const controller=new AbortController();c.abort=controller;const deadline=setTimeout(()=>controller.abort(),8000);
          try{const data=await scRequest('frame',blob,controller.signal);scAccept(data,generation);}
          finally{clearTimeout(deadline);if(c.abort===controller)c.abort=null;}
        }
      }catch(error){
        if(generation!==c.generation)return;
        if(error.status===401||error.status===403){stopServerCamera('会话失效，已停止上传，请重新登录。',false);return;}
        if(error.status===410){await viewServerCameraResult();if(c.phase==='running')stopServerCamera('本次入口已失效。',false);return;}
        scMessage('画面上传暂未成功，正在重连；服务器断流 10 秒后会自动停止。');
      }
      if(generation===c.generation&&c.phase==='running')c.timer=setTimeout(upload,c.frameInterval);
    };
    c.poll=setInterval(()=>{if(generation===c.generation)void viewServerCameraResult();},1000);
    void upload();
  }catch(error){
    if(generation!==c.generation)return;
    stopServerCamera(error.name==='NotAllowedError'?'摄像头权限尚未允许，请允许后重新开始。':error.message);
  }
}
async function initializeServerScanLink(){
  const c=serverCamera;c.capability=true;
  const token=location.hash.slice(1);history.replaceState(null,'',location.pathname);
  sc('server-camera-start').disabled=true;
  try{
    const response=await fetch('/scan-api/claim',{method:'POST',credentials:'same-origin',cache:'no-store',
      headers:{'Content-Type':'application/json','X-Scan-Request':'1'},body:JSON.stringify({token})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'入口已失效');
    c.csrf=data.csrf;c.deadline=performance.now()+data.remaining_seconds*1000;
    scMessage('入口已领取。点击开始扫描，画面发送服务器；在下方查看签到结果。');renderServerCameraState();
    c.expiry=setInterval(()=>{
      const remaining=Math.max(0,Math.ceil((c.deadline-performance.now())/1000));
      if(sc('remaining'))sc('remaining').textContent=`剩余 ${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')}`;
      if(!remaining){stopServerCamera('本次入口已超时。');c.phase='ended';clearInterval(c.expiry);renderServerCameraState();}
    },250);
  }catch(error){c.phase='ended';scMessage(error.message);renderServerCameraState();}
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('#server-camera-start,#server-camera-stop,#server-camera-result');if(!button)return;
  if(button.id==='server-camera-start')void startServerCamera();
  if(button.id==='server-camera-stop'){
    const stopping=serverCamera.runId||serverCamera.capability?scRequest('stop').catch(()=>null):Promise.resolve();
    stopServerCamera('扫描已停止，正在读取结果。',false);
    if(serverCamera.capability){serverCamera.phase='ended';renderServerCameraState();}
    await stopping;void viewServerCameraResult();
  }
  if(button.id==='server-camera-result')void viewServerCameraResult();
});
window.addEventListener('pagehide',()=>stopServerCamera('',true));
document.addEventListener('visibilitychange',()=>{if(document.hidden&&(serverCamera.phase==='running'||serverCamera.busy))stopServerCamera('页面已进入后台，手机和服务器扫描已停止。');});
if(document.querySelector('[data-scan-capability]'))void initializeServerScanLink();
