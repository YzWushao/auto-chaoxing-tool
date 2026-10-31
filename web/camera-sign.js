/* Browser-owned camera session. Only decoded QR text is sent to our sign API. */
'use strict';
const cameraSession={running:false,starting:false,generation:0,stream:null,worker:null,timer:null,decodeTimer:null,
  decoding:false,frameAt:0,latest:null,queue:null,busy:false,scanIntervalMs:100,blocked:[],attention:null,verification:null,requirement:null,proof:null,faceProof:null,faceTarget:null,facePaused:false,mode:'camera',imageAbort:null,message:'选择用户后，点击按钮申请摄像头权限。',scanMessage:'尚未识别签到二维码'};

function newCameraQueue(accounts){
  const c=cameraSession,p=state.preferences||{},interval=Number(p.camera_scan_interval??0.1);
  c.queue=new SignCameraQueue.Queue(accounts,p.camera_concurrency??1);
  c.scanIntervalMs=Number.isFinite(interval)&&interval>=0.05&&interval<=10?Math.round(interval*1000):100;
}

function cameraAccountFinished(account){
  const c=cameraSession;
  if(c.proof?.account===account)c.proof=null;
  if(c.faceProof?.account===account)c.faceProof=null;
  if(c.attention===account){c.attention=null;c.requirement=null;c.verification=null;c.faceTarget=null;}
  c.blocked=c.blocked.filter(value=>value.entry.id!==account);
}

function activateCameraAttention(){
  const c=cameraSession,q=c.queue;
  if(c.attention||!q||!c.blocked.length)return;
  const {entry,error}=c.blocked.shift();
  if(!q.order.includes(entry.id))return activateCameraAttention();
  q.focus(entry.id);c.attention=entry.id;c.message=`${entry.name}：${error.message}`;
  // Only the selected account may own the visible verification / photo context.
  if(c.proof?.account!==entry.id)c.proof=null;
  if(c.faceProof?.account!==entry.id){c.faceProof=null;c.faceTarget=null;}
  if(error.code==='verification_required'){
    c.verification={account:entry.id};c.requirement=null;c.proof=null;
    showSignVerification('camera',entry.id,error.verification);
  }else{
    c.verification=null;c.requirement=error.code;
    c.message+='；处理后点击“处理后继续重试”。';
    if(error.code!=='location_required')c.faceTarget=error.activity||{id:q.activityId,source:'course'};
  }
}

function cameraSignEntry(){
  return `<section class="notice purple"><b>连续扫码签到</b><p>选择用户，使用本设备摄像头持续识别二维码，按设置的并发数提交，并分别显示每位用户的结果。</p><a class="button secondary small" href="#sign-camera">进入摄像头扫码签到 →</a></section>`;
}

function cameraSignPage(){
  if(!cameraSession.queue)cameraSession.message='选择用户后，点击按钮申请摄像头权限。';
  return heading('摄像头扫码签到','选择本次需要签到的用户，然后将摄像头对准签到二维码。','<a class="button secondary" href="#sign">返回签到中心</a>')+
  `<div id="camera-sign-root"><div class="camera-layout"><section class="panel"><div class="panel-header"><h3>1 · 选择用户</h3><span class="badge purple">最多 ${state.preferences?.camera_concurrency??1} 人并发</span></div><div class="panel-body"><div class="actions">${button('全选','camera-select-all','secondary small')}${button('清空','camera-select-none','secondary small')}</div><div class="camera-choice-list">${state.accounts.map(a=>`<label class="camera-choice"><input type="checkbox" name="camera-user" value="${esc(a.id)}"><span>${esc(a.name)}${a.status==='expired'?'<small>登录已失效，请先重新登录</small>':''}</span></label>`).join('')||'<p class="muted">请先在用户管理中添加超星账户。</p>'}</div><p class="setting-note">失败超过 10 次即本轮第 11 次失败后，移至待处理队列末尾，再处理下一位；并发槽位可同时处理其他用户，成功用户退出队列。失败用户轮到时重新计数，累计失败仍保留。</p><div class="field"><label for="camera-location">二维码附加位置（按需选择实际所在点位）</label><select id="camera-location"><option value="">不提交位置</option>${(state.location_presets||[]).flatMap(s=>s.points.map(p=>`<option value="${esc(JSON.stringify([s.school,p.name]))}">${esc(s.school+' · '+p.name)}</option>`)).join('')}</select></div><div class="camera-control"><select id="camera-facing" aria-label="优先使用的摄像头"><option value="environment">后置摄像头优先</option><option value="user">前置摄像头优先</option></select>${button('启动摄像头并开始','camera-start','primary')}${button('停止并释放摄像头','camera-stop','secondary')}${button('处理后继续重试','camera-resume','secondary')}${button('准备当前用户照片','camera-face','secondary')}${button('核对官方完成结果','camera-confirm','secondary')}${button('从相册识别并开始','camera-image','secondary')}<input id="camera-image-file" type="file" class="hidden" accept="image/png,image/jpeg,image/webp"></div><p id="camera-error" class="inline-error" role="alert"></p><p class="setting-note camera-help">扫码画面只在本设备内识别，不录制、不上传；本人照片仅在单独确认后发送超星。启动即按选择的用户自动提交；滑块验证可在此完成；人脸可准备本人照片；官方活体或设备校验需转官方处理。停止、离开页面、切到后台或全部完成时关闭摄像头；已发出的请求仍会返回结果。</p><div class="notice camera-help">远程实时摄像头需通过 HTTPS 访问，相册扫码可直接使用当前地址。本机可使用 localhost / 127.0.0.1；普通 HTTP 的局域网或 P2P IP 无法申请摄像头权限。</div></div></section><section class="panel"><div class="panel-header"><h3>2 · 持续扫码</h3><span id="camera-live-badge" class="badge">摄像头未开启</span></div><div class="panel-body"><div class="camera-preview"><video id="sign-camera-video" autoplay muted playsinline aria-label="本设备摄像头预览"></video><p>允许摄像头后，将签到二维码置于画面中央。</p><img id="camera-image-preview" class="camera-photo hidden" alt="本地二维码图片预览"></div><div id="camera-hardware" class="camera-hardware hidden"><label id="camera-torch-wrap" class="hidden"><input type="checkbox" id="camera-torch">补光灯</label><label id="camera-zoom-wrap" class="hidden">变焦 <input type="range" id="camera-zoom" min="1" max="1" step="0.1" value="1" aria-label="摄像头变焦"></label></div><p id="camera-scan-status" class="setting-note" role="status"></p><div id="camera-status" class="camera-status" role="status" aria-live="polite"></div><div id="camera-verification"></div><div id="camera-summary" class="camera-summary"></div><ol id="camera-queue" class="camera-queue" aria-label="签到队列"></ol></div></section></div></div>`;
}

function renderCameraStatus(){
  const root=$('#camera-sign-root');if(!root)return;
  const c=cameraSession,q=c.queue,locked=c.running||c.starting||c.busy||c.facePaused;
  $$('[name="camera-user"],#camera-facing,[data-action="camera-select-all"],[data-action="camera-select-none"]',root).forEach(el=>el.disabled=locked);
  $('[data-action="camera-start"]',root).disabled=locked;
  $('[data-action="camera-stop"]',root).disabled=!(c.running||c.starting||c.facePaused);
  $('[data-action="camera-image"]',root).disabled=c.facePaused||c.starting||(c.busy&&!c.running)||(c.running&&c.mode!=='image');
  $('[data-action="camera-image"]',root).textContent=c.running&&c.mode==='image'?'更新二维码图片':'从相册识别并开始';
  $('[data-action="camera-resume"]',root).disabled=!c.facePaused&&(!c.running||!c.requirement);
  $('[data-action="camera-face"]',root).disabled=c.busy||!c.faceTarget||!['face_required','official_face_required'].includes(c.requirement);
  $('[data-action="camera-confirm"]',root).disabled=c.busy||!c.faceTarget||!q?.current;
  $('#camera-live-badge').textContent=c.facePaused?'扫码镜头已暂时释放':c.starting?'正在启动 / 识别':c.running?(c.mode==='image'?'相册扫码中':'摄像头已开启'):'摄像头未开启';
  $('#camera-live-badge').className='badge'+(c.running?' green':'');
  $('#camera-status').textContent=c.message;
  $('#camera-scan-status').textContent=(q?.activityId?`本次活动 ${q.activityId} · `:'')+c.scanMessage;
  if(!q){$('#camera-summary').textContent='尚未建立队列';$('#camera-queue').replaceChildren();return;}
  $('#camera-summary').innerHTML=`<span>已完成 <b>${q.entries.filter(a=>a.status==='succeeded').length} / ${q.entries.length}</b></span><span>待处理 <b>${q.order.length}</b></span><span>正在提交 <b>${q.inFlight.size} / ${q.concurrency}</b></span><span>当前用户本轮失败 <b>${q.current?.passFailures||0} / 11</b></span>`;
  $('#camera-queue').innerHTML=q.rows().map((a,index)=>`<li class="${a.status==='submitting'||q.current?.id===a.id?'current':''}"><div class="camera-row-head"><strong>${index+1}. ${esc(state.accounts.find(x=>x.id===a.id)?.name||a.name)}</strong><span class="badge ${a.status==='succeeded'?'green':a.status==='submitting'?'purple':''}">${a.status==='succeeded'?'已签到':a.status==='submitting'?'正在提交':a.status==='waiting'?'等待处理验证':q.current?.id===a.id?'下一位 / 重试中':'等待'}</span></div><p>提交 ${a.attempts} 次 · 累计失败 ${a.failures} 次 · 本轮失败 ${a.passFailures} / 11${a.rotations?` · 已移至队尾 ${a.rotations} 次`:''}</p><p class="${a.failures&&a.status!=='succeeded'?'camera-failure':''}">${esc(a.message)}</p></li>`).join('');
}

function closeSignCamera(message){
  const c=cameraSession;
  c.running=false;c.starting=false;c.generation++;clearTimeout(c.timer);clearTimeout(c.decodeTimer);
  c.worker?.terminate();c.worker=null;c.decoding=false;c.latest=null;
  c.imageAbort?.abort();c.imageAbort=null;c.blocked=[];c.attention=null;c.verification=null;c.requirement=null;c.proof=null;c.faceProof=null;c.faceTarget=null;c.facePaused=false;closeSignFace('camera');clearSignVerification('camera');
  const photo=$('#camera-image-preview');if(photo){photo.removeAttribute('src');photo.classList.add('hidden');}
  c.stream?.getTracks().forEach(track=>track.stop());c.stream=null;
  const video=$('#sign-camera-video');if(video){video.pause();video.srcObject=null;delete video.dataset.live;}
  $('#camera-hardware')?.classList.add('hidden');
  if(message)c.message=message+(c.busy?'；已发出的请求仍在等待结果。':'');
  renderCameraStatus();
}

function cameraError(error){
  return ({NotAllowedError:'摄像头权限未获允许，请在浏览器站点设置中允许后重试。',NotFoundError:'未找到可用摄像头，请检查设备连接。',NotReadableError:'摄像头无法启动，可能正被其他程序占用。',OverconstrainedError:'当前摄像头不支持所需画面，请切换摄像头后重试。',SecurityError:'浏览器禁止使用摄像头，请检查 HTTPS 与站点权限。'})[error.name]||'摄像头无法启动，请检查浏览器权限和设备连接。';
}

async function startSignCamera(resume=false){
  const c=cameraSession;if(c.running||c.starting||c.busy)return;
  const selected=new Set(resume&&c.queue?c.queue.entries.map(a=>a.id):$$('[name="camera-user"]:checked').map(el=>el.value));
  $('#camera-error').textContent='';
  if(!selected.size){$('#camera-error').textContent='请至少选择一个需要签到的用户。';return;}
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){$('#camera-error').textContent='当前地址无法使用摄像头。请通过 HTTPS 访问，或在运行服务的本机使用 localhost / 127.0.0.1。';return;}
  if(!resume)closeSignCamera();else{c.generation++;c.facePaused=false;c.latest=null;}
  const accounts=state.accounts.filter(a=>selected.has(a.id));
  if(!accounts.length){$('#camera-error').textContent='所选用户已被移除，请刷新页面后重新选择。';return;}
  if(!resume)newCameraQueue(accounts);
  c.mode='camera';
  c.starting=true;c.message='等待浏览器摄像头权限，请选择允许。';c.scanMessage='尚未识别签到二维码';
  const generation=c.generation;renderCameraStatus();
  try{
    const facingMode=$('#camera-facing').value;
    const stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:facingMode},width:{ideal:1280},height:{ideal:720}}});
    if(generation!==c.generation||state.page!=='sign-camera'){stream.getTracks().forEach(track=>track.stop());return;}
    c.stream=stream;const video=$('#sign-camera-video');video.srcObject=stream;await video.play();
    if(generation!==c.generation)return;
    video.dataset.live='true';c.starting=false;c.running=true;c.message='摄像头已开启，等待签到二维码。';
    configureCameraHardware(stream.getVideoTracks()[0]);
    stream.getVideoTracks().forEach(track=>track.addEventListener('ended',()=>{if(c.running&&generation===c.generation)closeSignCamera('摄像头已断开，请重新启动。');}));
    const canvas=document.createElement('canvas'),context=canvas.getContext('2d',{willReadFrequently:true});
    if(!context)throw new Error('canvas');
    const worker=new Worker('/static/sign-qr-worker.js?v=0.5.0');c.worker=worker;
    worker.onerror=()=>closeSignCamera('二维码识别组件无法运行，请刷新页面后重试。');
    worker.onmessage=event=>{
      if(!c.running||generation!==c.generation)return;
      clearTimeout(c.decodeTimer);c.decoding=false;
      const value=SignCameraQueue.parameters(event.data?.text);
      if(!value){c.latest=null;c.scanMessage=event.data?.text?'这不是可用于自动签到的二维码。':'等待识别签到二维码';}
      else if(Date.now()-c.frameAt>1500){c.latest=null;c.scanMessage='识别画面已滞后，请将二维码靠近镜头并保持清晰。';}
      else if(!c.queue.bind(value.activityId)){c.latest=null;c.scanMessage='识别到其他活动，请继续对准本次活动；更换活动需停止后重新开始。';}
      else{c.latest={...value,at:c.frameAt};c.scanMessage='已识别，持续读取最新二维码';}
      renderCameraStatus();void submitCameraNext(generation);
    };
    const scan=()=>{
      if(!c.running||generation!==c.generation)return;
      c.timer=setTimeout(scan,c.scanIntervalMs);
      if(c.decoding||video.readyState<2||!video.videoWidth)return;
      try{
        const scale=Math.min(1,1280/Math.max(video.videoWidth,video.videoHeight));
        canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale));
        context.drawImage(video,0,0,canvas.width,canvas.height);
        const pixels=context.getImageData(0,0,canvas.width,canvas.height).data;
        c.frameAt=Date.now();c.decoding=true;c.decodeTimer=setTimeout(()=>closeSignCamera('二维码识别超时，请重新启动摄像头。'),8000);
        worker.postMessage({pixels:pixels.buffer,width:canvas.width,height:canvas.height},[pixels.buffer]);
      }catch{closeSignCamera('无法读取摄像头画面，请重新启动。');}
    };
    renderCameraStatus();scan();
  }catch(error){
    if(generation!==c.generation)return;
    closeSignCamera('摄像头未开启。');if($('#camera-error'))$('#camera-error').textContent=cameraError(error);
  }
}

async function submitCameraNext(generation){
  const c=cameraSession,q=c.queue,qr=c.latest;
  if(!c.running||c.starting||generation!==c.generation||c.busy||!q)return;
  activateCameraAttention();
  if(c.verification||c.requirement||q.done||!qr||(c.mode!=='image'&&Date.now()-qr.at>1500))return;
  const entries=[],now=Date.now();
  if(c.attention){
    const selected=q.entries.find(value=>value.id===c.attention);
    if(selected?.status==='waiting')selected.status='pending';
    const entry=q.begin(c.attention,now);if(entry)entries.push(entry);
  }else{
    let entry;while((entry=q.begin(null,now)))entries.push(entry);
  }
  if(!entries.length)return;
  c.busy=true;c.message=`正在为 ${entries.map(entry=>entry.name).join('、')} 提交签到（${entries.length} / ${q.concurrency} 并发）。`;renderCameraStatus();
  // A batch drains before another is started or a verification UI is shown.
  // Each response is attributed by account ID, never by completion order.
  try{
    await Promise.allSettled(entries.map(entry=>submitCameraAccount(entry,qr,generation,q)));
  }finally{
    c.busy=false;
    if(c.running&&generation===c.generation){
      activateCameraAttention();
      if(q.done)closeSignCamera('所选用户已全部签到，摄像头已关闭。');
    }
    renderCameraStatus();
  }
}

async function submitCameraAccount(entry,qr,generation,q){
  const c=cameraSession;
  try{
    const payload={qr:qr.raw};if(c.proof?.account===entry.id)payload.verification_id=c.proof.id;
    if(c.faceProof?.account===entry.id)payload.face_id=c.faceProof.id;
    const location=$('#camera-location')?.value;if(location){const [school,name]=JSON.parse(location);payload.location={school,name};}
    const result=await api(`/accounts/${encodeURIComponent(entry.id)}/camera-sign`,'POST',payload);
    q.finish(true,result.message,entry.id);cameraAccountFinished(entry.id);c.message=`${entry.name}：${result.message}`;
  }catch(error){
    if(error.status===400){if(c.faceProof?.account===entry.id)c.faceProof=null;if(c.proof?.account===entry.id)c.proof=null;}
    const needsAttention=(error.code==='verification_required'&&error.verification)||(error.status===422&&['face_required','official_face_required','location_required'].includes(error.code));
    if(needsAttention){
      q.defer(error.message,entry.id);
      if(c.running&&generation===c.generation){
        entry.status='waiting';
        if(c.attention===entry.id){c.attention=null;c.blocked.unshift({entry,error});}
        else c.blocked.push({entry,error});
      }
    }
    else if(error.status===429){q.defer(error.message,entry.id);c.message=`${entry.name}：${error.message}`;}
    else{
      const outcome=q.finish(false,error.message,entry.id);cameraAccountFinished(entry.id);
      c.message=outcome.moved?`${entry.name} 本轮已失败 11 次，已放到队尾；继续其他用户。`:`${entry.name}：${error.message}`;
      // A lost HTTP response can mean the platform already accepted the request.
      if(!error.status||error.status===401||error.status===403)closeSignCamera('连接或控制台会话异常，已停止；请核对结果后重新开始。');
    }
    entry.retryAt=Date.now()+2500;
  }
  renderCameraStatus();
}

function suspendCameraForFace(){
  const c=cameraSession;c.facePaused=true;c.running=false;c.generation++;clearTimeout(c.timer);clearTimeout(c.decodeTimer);c.worker?.terminate();c.worker=null;c.decoding=false;
  if(c.mode!=='image')c.latest=null;
  c.stream?.getTracks().forEach(t=>t.stop());c.stream=null;
  const video=$('#sign-camera-video');if(video){video.pause();video.srcObject=null;delete video.dataset.live;}
  $('#camera-hardware')?.classList.add('hidden');
  renderCameraStatus();
}
function resumeCameraAfterFace(){
  const c=cameraSession;if(!c.facePaused)return;
  if(['face_required','official_face_required'].includes(c.requirement)&&!c.faceProof){toast('请先准备当前用户照片，或核对官方完成结果。',true);return;}
  closeSignFace('camera');c.requirement=null;
  if(c.mode==='image'){
    c.facePaused=false;c.running=true;c.generation++;const generation=c.generation;
    const tick=()=>{if(!c.running||generation!==c.generation)return;c.timer=setTimeout(tick,c.scanIntervalMs);void submitCameraNext(generation);};tick();renderCameraStatus();
  }else void startSignCamera(true);
}

function configureCameraHardware(track){
  const caps=track?.getCapabilities?.()||{},box=$('#camera-hardware');if(!box)return;
  box.classList.toggle('hidden',!caps.torch&&!caps.zoom);
  $('#camera-torch-wrap').classList.toggle('hidden',!caps.torch);$('#camera-torch').checked=false;
  $('#camera-zoom-wrap').classList.toggle('hidden',!caps.zoom);
  if(caps.zoom){const range=$('#camera-zoom');range.min=caps.zoom.min;range.max=caps.zoom.max;range.step=caps.zoom.step||0.1;range.value=track.getSettings?.().zoom||caps.zoom.min;}
}

async function startImageSign(file){
  if(!file)return;
  const c=cameraSession;if(c.starting||(c.busy&&!c.running)||(c.running&&c.mode!=='image'))return;
  $('#camera-error').textContent='';
  if(!c.running){
    const ids=new Set($$('[name="camera-user"]:checked').map(el=>el.value)),accounts=state.accounts.filter(a=>ids.has(a.id));
    if(!accounts.length){$('#camera-error').textContent='请先选择需要签到的用户。';return;}
    closeSignCamera();newCameraQueue(accounts);c.mode='image';
  }
  const generation=c.generation,controller=new AbortController();c.imageAbort?.abort();c.imageAbort=controller;c.starting=true;renderCameraStatus();
  try{
    const decoded=await SignQR.decodeImage(file,{signal:controller.signal}),value=SignCameraQueue.parameters(decoded.raw);
    if(generation!==c.generation)return;
    if(!value)throw new Error('图片中不是可用于自动签到的二维码');
    if(!c.queue.bind(value.activityId))throw new Error('此图片属于其他活动，请停止后重新开始');
    const image=$('#camera-image-preview');image.src=decoded.preview;image.classList.remove('hidden');
    c.latest={...value,at:Date.now()};c.running=true;c.starting=false;c.message='相册二维码已识别，开始按队列提交。';c.scanMessage='相册模式，可随时更新二维码图片';
    const tick=()=>{if(!c.running||generation!==c.generation)return;c.timer=setTimeout(tick,c.scanIntervalMs);void submitCameraNext(generation);};
    clearTimeout(c.timer);tick();
  }catch(error){if(generation===c.generation&&error.name!=='AbortError')$('#camera-error').textContent=error.message;}
  finally{if(generation===c.generation){c.starting=false;renderCameraStatus();}}
}

document.addEventListener('click',event=>{
  const target=event.target.closest('[data-action]');if(!target)return;
  const action=target.dataset.action;
  if(action==='camera-start')void startSignCamera();
  if(action==='camera-stop')closeSignCamera('已停止并释放摄像头。');
  if(action==='camera-image')$('#camera-image-file').click();
  if(action==='camera-resume'){if(cameraSession.facePaused)return resumeCameraAfterFace();cameraSession.requirement=null;cameraSession.message='等待二维码后继续当前用户。';renderCameraStatus();}
  if(action==='camera-face'){const c=cameraSession,target=c.faceTarget;if(target&&c.queue?.current)showSignFace('camera',c.queue.current.id,target.id,target.source);}
  if(action==='camera-confirm'){const c=cameraSession,info=c.faceTarget;if(info&&c.queue?.current)void busy(target,()=>confirmSignResult(c.queue.current.id,info.id,info.source,'camera'));}
  if(action==='camera-select-all'||action==='camera-select-none'){
    if(cameraSession.running||cameraSession.starting||cameraSession.busy)return;
    $$('[name="camera-user"]').forEach(el=>el.checked=action==='camera-select-all');
    $('#camera-error').textContent='';
  }
});
document.addEventListener('change',async event=>{
  if(event.target.matches('[name="camera-user"],#camera-facing'))$('#camera-error').textContent='';
  if(event.target.id==='camera-image-file'){const file=event.target.files[0];event.target.value='';void startImageSign(file);}
  if(event.target.matches('#camera-torch,#camera-zoom')){
    const track=cameraSession.stream?.getVideoTracks()[0];if(!track)return;
    try{await track.applyConstraints({advanced:[{torch:$('#camera-torch').checked,zoom:Number($('#camera-zoom').value)}]});}
    catch{$('#camera-error').textContent='当前设备未能应用补光 / 变焦设置，请恢复后重试。';}
  }
});
window.addEventListener('pagehide',()=>closeSignCamera());
document.addEventListener('visibilitychange',()=>{if(document.hidden&&(cameraSession.running||cameraSession.starting))closeSignCamera('页面已进入后台，摄像头已关闭；回到页面后可重新开始。');});
