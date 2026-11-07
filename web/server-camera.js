/* Browser uploads JPEG; the Android app supplies native QR results to the same server queue. */
'use strict';
const serverCamera={generation:0,stream:null,runId:'',phase:'idle',busy:false,capability:false,pickUsers:false,csrf:'',
  timer:null,poll:null,expiry:null,abort:null,polling:false,pollGeneration:0,deadline:0,result:null,frameInterval:200,rowsKey:'',native:false,nativeBusy:false,zoomFrame:null,manualUsers:null};
const sc=id=>document.getElementById(id),scEsc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function serverCameraUserChoices(accounts){
  return accounts.map(a=>`<label class="camera-choice"><input type="checkbox" name="server-camera-user" value="${scEsc(a.id)}" ${a.status==='expired'?'disabled data-unavailable="true"':''}><span>${scEsc(a.name)}${a.status==='expired'?'<small>登录已失效</small>':''}</span></label>`).join('')||'<p>请先添加超星用户。</p>';
}
function selectedServerCameraUsers(){
  return [...document.querySelectorAll('[name="server-camera-user"]:checked')].map(el=>el.value);
}
function selectAllServerCameraUsers(){
  const c=serverCamera;
  if(c.busy||c.phase==='running'||(c.capability&&(!c.csrf||c.phase==='ended')))return;
  document.querySelectorAll('[name="server-camera-user"]').forEach(input=>{if(!input.disabled)input.checked=true;});
  renderServerCameraState();
}
function serverCameraLocationChoices(locations){
  return locations.map(p=>`<label class="camera-choice"><input type="radio" name="server-camera-location" value="${scEsc(p.id)}"><span>${scEsc(p.school+' · '+p.name)}<small>学校位置：${scEsc(p.address||p.school)}</small></span></label>`).join('')||'<p class="setting-note">暂无预设点位，请先到设置创建学校、填写学校位置并添加点位。</p>';
}
function serverCameraLocationControls(locations){
  return `<section id="server-camera-location-panel"><label class="camera-switch"><input type="checkbox" id="server-camera-report-location" role="switch">上报位置</label><div id="server-camera-device-controls" hidden></div><div class="camera-location-list" id="server-camera-location-list" hidden>${serverCameraLocationChoices(locations)}</div><p class="setting-note">关闭时不提交位置；预设点位的位置说明统一使用学校位置。</p></section>`;
}
function selectedServerCameraLocation(){
  if(!sc('server-camera-report-location')?.checked)return null;
  if(useDeviceLocation())return null;
  const value=document.querySelector('[name="server-camera-location"]:checked')?.value;
  if(!value)throw new Error('已开启上报位置，请选择一个点位。');
  if(serverCamera.capability)return value;
  const [school,name]=JSON.parse(value);return {school,name};
}
function serverCameraPage(){
  return heading(window.AndroidScanner?'安卓原生扫码签到':'服务器扫码签到',window.AndroidScanner?'手机原生识别并描框，服务器管理用户队列并执行签到。':'手机仅上传连续 JPEG 画面；识别二维码、用户队列和签到提交均在服务器执行。','<a class="button secondary" href="#sign">返回签到中心</a>')+
    `<div id="server-camera-root"><div class="camera-layout"><section class="panel"><div class="panel-header"><h3>选择本次用户</h3><div class="camera-user-actions"><label class="camera-switch"><input type="checkbox" id="server-camera-select-all" role="switch">全选用户</label><span class="badge purple">最多 ${state.preferences?.camera_concurrency??5} 人并发</span></div></div><div class="panel-body"><p class="setting-note" id="server-camera-user-summary"></p><div class="camera-choice-list" id="server-camera-user-list">${serverCameraUserChoices(state.accounts)}</div>${serverCameraLocationControls((state.location_presets||[]).flatMap(s=>s.points.map(p=>({id:JSON.stringify([s.school,p.name]),school:s.school,name:p.name,address:s.address||s.school}))))}<p class="setting-note">${window.AndroidScanner?'相机画面留在安卓本机，原生识别后仅发送二维码结果；服务器执行签到。':'画面发往当前服务器，在内存识别，不录像、不保存图片，仅保留最新一帧。'}超星验证码继续使用现有自动验证流程；需要人工处理时会在结果中提示。</p><p class="setting-note">停止、离开页面或切后台会结束扫描；断流 10 秒后服务器自动停止。已发出的签到请求仍可能返回结果。</p></div></section><section class="panel"><div class="panel-header"><h3>连续扫码 · 服务器处理</h3></div><div class="panel-body">${serverCameraControls()}</div></section></div></div>`;
}
function serverCameraControls(){
  return '<div class="camera-preview server-camera-preview"><video id="server-camera-video" autoplay muted playsinline aria-label="本机摄像头预览"></video><canvas id="server-camera-zoom-preview" class="camera-zoom-preview" aria-label="放大后的扫码画面" hidden></canvas><svg id="server-camera-outline" class="qr-outline" preserveAspectRatio="xMidYMid meet" role="img" aria-label="服务器识别到的二维码位置" hidden><polygon vector-effect="non-scaling-stroke"></polygon></svg><p>开始后允许摄像头，将二维码放入画面。</p></div>'+serverCameraZoomControls()+'<div class="camera-control"><button type="button" class="button primary" id="server-camera-start">开始扫描</button><button type="button" class="button secondary" id="server-camera-stop" disabled>停止扫描</button><button type="button" class="button secondary" id="server-camera-result">查看结果</button></div><p id="server-camera-status" class="camera-status" role="status" aria-live="polite">点击开始扫描，画面将上传至本项目服务器。</p><p id="server-camera-counter" class="setting-note"></p><ol id="server-camera-results" class="camera-queue" aria-label="服务器签到结果"></ol>';
}
function serverCameraZoomControls(){
  return '<div class="server-camera-zoom"><div class="server-camera-zoom-heading"><label for="server-camera-zoom">放大倍数</label><output id="server-camera-zoom-value" for="server-camera-zoom">1.0×</output></div><input id="server-camera-zoom" type="range" min="1" max="5" step="0.1" value="1" aria-label="扫码画面放大倍数"><p id="server-camera-zoom-note" class="setting-note">1×–5× 画面放大，预览与服务器识别画面同步。</p></div>';
}
function serverCameraZoom(){
  return Math.min(5,Math.max(1,Number(sc('server-camera-zoom')?.value)||1));
}
function updateServerCameraZoom(){
  const range=sc('server-camera-zoom'),value=sc('server-camera-zoom-value'),note=sc('server-camera-zoom-note');
  if(value)value.textContent=serverCameraZoom().toFixed(1)+'×';
  if(range)range.disabled=serverCamera.native||Boolean(window.AndroidScanner);
  if(note)note.textContent=window.AndroidScanner?'安卓原生相机已提供倍率滑块，请在原生相机下方调节。':'1×–5× 画面放大，预览与服务器识别画面同步。';
}
function startServerCameraZoomPreview(generation){
  const c=serverCamera,video=sc('server-camera-video'),canvas=sc('server-camera-zoom-preview');
  const context=canvas?.getContext?.('2d',{alpha:false});
  if(!context||typeof requestAnimationFrame!=='function')return;
  let previous=0;
  function draw(now){
    if(generation!==c.generation||c.phase!=='running')return;
    const zoom=serverCameraZoom();
    canvas.hidden=zoom<=1;video.classList.toggle('camera-digital-zoom',zoom>1);
    if(zoom>1&&video.readyState>=2&&video.videoWidth&&now-previous>=50){
      QRVision.draw(video,canvas,context,zoom,1280);previous=now;
    }
    c.zoomFrame=requestAnimationFrame(draw);
  }
  c.zoomFrame=requestAnimationFrame(draw);
}
function scHeaders(jpeg=false){
  const headers={'Content-Type':jpeg?'image/jpeg':'application/json'};
  if(serverCamera.capability){headers['X-Scan-Request']='1';headers['X-Scan-CSRF']=serverCamera.csrf;}
  else headers['X-CSRF-Token']=state.csrf;
  return headers;
}
function scPath(action){
  const c=serverCamera;
  if(c.capability)return '/scan-api/'+({start:'start',frame:'frame',qr:'qr',status:'status',stop:'close'}[action]);
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
  const deviceControls=sc('server-camera-device-controls');
  if(deviceControls){
    const supported=Boolean(window.DevicePosition?.available()||window.AndroidScanner?.deviceLocationAvailable);
    deviceControls.hidden=!sc('server-camera-report-location')?.checked;
    if(!deviceControls.dataset.ready){deviceControls.innerHTML='<label class="camera-switch"><input type="checkbox" id="server-camera-use-device-location">使用设备位置上报</label><p id="server-camera-device-status" class="setting-note">开始扫描时申请定位权限并获取当前位置，仅用于本次扫码；需 HTTPS 或本机 localhost。重新开始会重新定位。</p>';deviceControls.dataset.ready='true';}
    if(sc('server-camera-use-device-location'))sc('server-camera-use-device-location').disabled=!supported||serverCamera.busy||serverCamera.phase==='running';
  }
  if(!sc('server-camera-root'))return;
  const c=serverCamera,locked=c.phase==='running'||c.busy;
  updateServerCameraZoom();
  sc('server-camera-start').disabled=locked||(c.capability&&(!c.csrf||c.phase==='ended'||(c.pickUsers&&!selectedServerCameraUsers().length)));
  sc('server-camera-stop').disabled=!(locked||(c.capability&&c.csrf&&c.phase!=='ended'));
  const selectAll=sc('server-camera-select-all');
  if(selectAll)selectAll.disabled=locked||(c.capability&&(!c.csrf||c.phase==='ended'));
  if(sc('server-camera-user-list'))sc('server-camera-user-list').hidden=Boolean(selectAll?.checked);
  if(sc('server-camera-user-summary'))sc('server-camera-user-summary').textContent=selectAll?.checked?`已全选 ${selectedServerCameraUsers().length} 位可用用户；关闭开关可手动选择。`:`已选择 ${selectedServerCameraUsers().length} 位用户`;
  if(sc('server-camera-location-list'))sc('server-camera-location-list').hidden=!sc('server-camera-report-location')?.checked||useDeviceLocation();
  document.querySelectorAll('[name="server-camera-user"],[name="server-camera-location"],#server-camera-report-location').forEach(input=>input.disabled=locked||(c.capability&&c.phase==='ended')||input.dataset.unavailable==='true');
  if(!data)return;
  scMessage(data.message);
  sc('server-camera-counter').textContent=c.native?`原生识别 · 已接收 ${data.decoded_frames||0} 次有效二维码`:`已接收 ${data.frames||0} 帧 · 已识别 ${data.decoded_frames||0} 帧`;
  const rowsKey=JSON.stringify(data.accounts||[]);
  if(c.rowsKey!==rowsKey){
    sc('server-camera-results').innerHTML=(data.accounts||[]).map(a=>`<li><div class="camera-row-head"><strong>${scEsc(a.name)}</strong><span class="badge ${a.state==='succeeded'?'green':'purple'}">${scEsc(a.state==='pending'&&a.retry_code==='location_rejected'?'上报失败 · 等待重试':({succeeded:'签到成功',waiting:'需要处理',submitting:'正在签到',pending:'等待扫码'}[a.state]||a.state))}</span></div><p>${scEsc(a.message)} · 提交 ${a.attempts} 次 · 失败 ${a.failures} 次</p></li>`).join('');
    c.rowsKey=rowsKey;
  }
  QRVision.outline(sc('server-camera-outline'),c.phase==='running'?data.detection:null);
}
function scRelease(){
  window.AndroidScanner?.cancelLocation?.();
  const c=serverCamera;c.generation++;clearTimeout(c.timer);clearInterval(c.poll);c.abort?.abort();c.abort=null;
  if(c.native)window.AndroidScanner?.stop();c.nativeBusy=false;
  if(typeof cancelAnimationFrame==='function')cancelAnimationFrame(c.zoomFrame);c.zoomFrame=null;
  c.stream?.getTracks().forEach(track=>track.stop());c.stream=null;c.busy=false;c.polling=false;
  const video=sc('server-camera-video');if(video){video.pause();video.srcObject=null;delete video.dataset.live;}
  video?.classList?.remove('camera-digital-zoom');
  if(sc('server-camera-zoom-preview'))sc('server-camera-zoom-preview').hidden=true;
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
  const accounts=c.capability&&!c.pickUsers?[]:selectedServerCameraUsers();
  if((!c.capability||c.pickUsers)&&!accounts.length){scMessage('请先选择本次需要签到的用户。');return;}
  let location;try{location=selectedServerCameraLocation();}catch(error){scMessage(error.message);return;}
  if(window.AndroidScanner){await startAndroidCamera(accounts,location);return;}
  c.native=false;
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){scMessage('摄像头需要 HTTPS，请在系统浏览器中打开入口。');return;}
  c.busy=true;c.result=null;c.rowsKey='';c.runId='';const generation=++c.generation;renderServerCameraState();scMessage('请允许使用摄像头，开始后连续 JPEG 将上传到服务器。');
  try{
    let deviceLocation;
    if(useDeviceLocation()){
      c.locating=true;scMessage('正在获取设备当前位置，请允许定位权限…');
      try{deviceLocation=await window.DevicePosition.get();}finally{c.locating=false;}
      if(generation!==c.generation)return;
      if(document.hidden)throw new Error('页面已进入后台，请返回后重新开始');
      if(sc('server-camera-device-status'))sc('server-camera-device-status').textContent=`本次定位报告误差约 ${Math.ceil(deviceLocation.accuracy)} 米；重新开始可刷新位置。`;
    }
    const stream=await navigator.mediaDevices.getUserMedia(QRVision.constraints());
    if(generation!==c.generation){stream.getTracks().forEach(track=>track.stop());return;}
    c.stream=stream;const video=sc('server-camera-video');video.srcObject=stream;await video.play();
    if(generation!==c.generation)return;
    void QRVision.focus(stream.getVideoTracks()[0]);
    const payload={account_ids:accounts};if(location)payload.location=location;if(deviceLocation)payload.device_location=deviceLocation;
    const result=await scRequest('start',c.capability?(c.pickUsers?payload:{}):payload);
    if(generation!==c.generation){
      const path=c.capability?'/scan-api/close':`/api/camera-stream/${encodeURIComponent(result.id)}/stop`;
      void fetch(path,{method:'POST',credentials:'same-origin',headers:scHeaders(),body:'{}'}).catch(()=>{});return;
    }
    c.runId=result.id;c.frameInterval=Math.max(200,(result.frame_interval||.2)*1000);c.phase='running';c.busy=false;video.dataset.live='true';scAccept(result,generation);
    startServerCameraZoomPreview(generation);
    const canvas=document.createElement('canvas'),context=canvas.getContext('2d',{alpha:false});
    if(!context)throw new Error('当前浏览器无法读取摄像头画面');
    stream.getVideoTracks().forEach(track=>track.addEventListener('ended',()=>{if(generation===c.generation)stopServerCamera('摄像头断开，扫描已停止。');}));
    const upload=async()=>{
      if(generation!==c.generation||c.phase!=='running')return;
      try{
        if(video.readyState>=2&&video.videoWidth){
          const blob=await QRVision.jpeg(video,canvas,context,serverCameraZoom());
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
async function startAndroidCamera(accounts,location){
  const c=serverCamera;c.native=true;c.busy=true;c.result=null;c.rowsKey='';c.runId='';
  const generation=++c.generation;renderServerCameraState();scMessage('正在启动安卓原生相机，请允许摄像头权限。');
  try{
    let deviceLocation;
    if(useDeviceLocation()){
      scMessage('正在获取设备当前位置，请允许安卓定位权限…');
      deviceLocation=await (window.DevicePosition?.get()||window.AndroidScanner.getDeviceLocation());
      if(generation!==c.generation)return;
      if(sc('server-camera-device-status'))sc('server-camera-device-status').textContent=`本次使用设备位置，报告误差约 ${Math.ceil(deviceLocation.accuracy)} 米；停止后重新开始可刷新位置。`;
    }
    await window.AndroidScanner.start({interval:Math.max(100,(typeof state!=='undefined'?state.preferences?.camera_scan_interval||.1:.1)*1000),
      onClosed:message=>{if(generation===c.generation)stopServerCamera(message);},
      onScan:async qr=>{
        if(generation!==c.generation||c.phase!=='running'||c.nativeBusy)return;
        c.nativeBusy=true;const controller=new AbortController();c.abort=controller;
        const timeout=setTimeout(()=>controller.abort(),8000);
        try{scAccept(await scRequest('qr',{qr},controller.signal),generation);}
        catch(error){
          if(generation!==c.generation)return;
          if([401,403,410].includes(error.status))stopServerCamera(error.message,false);
          else if(error.status!==429)scMessage(error.message||'正在重新连接服务器');
        }finally{clearTimeout(timeout);if(c.abort===controller)c.abort=null;if(generation===c.generation)c.nativeBusy=false;}
      }});
    if(generation!==c.generation)return;
    const payload={account_ids:accounts,input:'native'};if(location)payload.location=location;if(deviceLocation)payload.device_location=deviceLocation;
    const result=await scRequest('start',c.capability?(c.pickUsers?payload:{input:'native'}):payload);
    if(generation!==c.generation){
      const path=c.capability?'/scan-api/close':`/api/camera-stream/${encodeURIComponent(result.id)}/stop`;
      void fetch(path,{method:'POST',credentials:'same-origin',headers:scHeaders(),body:'{}'}).catch(()=>{});return;
    }
    c.runId=result.id;c.phase='running';c.busy=false;
    window.AndroidScanner.configureInterval?.(Math.max(100,(result.frame_interval||.1)*1000));
    scAccept(result,generation);
    c.poll=setInterval(()=>{if(generation===c.generation)void viewServerCameraResult();},1000);
  }catch(error){if(generation===c.generation)stopServerCamera(error.message);}
}
function showServerScanCodeForm(){
  const c=serverCamera;
  if(c.csrf&&c.phase!=='ended')void fetch('/scan-api/close',{method:'POST',credentials:'same-origin',keepalive:true,headers:scHeaders(),body:'{}'}).catch(()=>{});
  scRelease();clearInterval(c.expiry);c.csrf='';c.runId='';c.result=null;c.phase='idle';c.pickUsers=false;c.rowsKey='';c.manualUsers=null;c.deadline=0;
  if(sc('scan-code-panel'))sc('scan-code-panel').hidden=false;
  sc('server-camera-root').hidden=true;
  for(const id of ['server-camera-user-list','server-camera-location-list','server-camera-results'])if(sc(id))sc(id).innerHTML='';
  sc('server-camera-select-all').checked=false;sc('server-camera-report-location').checked=false;
  sc('server-camera-counter').textContent='';if(sc('remaining'))sc('remaining').textContent='请输入验证码';
  renderServerCameraState();
}
async function verifyServerScanCode(code){
  const c=serverCamera;
  if(!/^[0-9]{8}$/.test(code))throw new Error('请输入8位纯数字验证码');
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
  let response,data;
  try{
    response=await fetch('/scan-api/verify',{method:'POST',credentials:'same-origin',cache:'no-store',signal:controller.signal,
      headers:{'Content-Type':'application/json','X-Scan-Request':'1'},body:JSON.stringify({code})});
    data=await response.json();
  }catch(error){throw new Error(error.name==='AbortError'?'验证请求超时，请重试；如验证码已使用，请回 QQ 获取新验证码。':'无法连接扫码服务，请稍后重试。');}
  finally{clearTimeout(timeout);}
  if(!response.ok)throw Object.assign(new Error(data.error||'验证码验证失败'),{status:response.status});
  c.phase='idle';c.runId='';c.result=null;c.rowsKey='';
  if(sc('scan-code-panel'))sc('scan-code-panel').hidden=true;
  sc('server-camera-root').hidden=false;
  c.csrf=data.csrf;c.deadline=performance.now()+data.remaining_seconds*1000;
  c.pickUsers=data.select_users===true;
  sc('server-camera-user-panel').hidden=!c.pickUsers;
  sc('server-camera-location-panel').hidden=!c.pickUsers;
  if(c.pickUsers){
    sc('server-camera-user-list').innerHTML=serverCameraUserChoices(data.accounts||[]);
    sc('server-camera-location-list').innerHTML=serverCameraLocationChoices(data.locations||[]);
    sc('server-camera-concurrency').textContent=`最多 ${data.concurrency||5} 人并发`;
  }
  scMessage(c.pickUsers?'请先勾选本次需要签到的用户，再点击开始扫描。':'验证成功。点击开始扫描，画面发送服务器；在下方查看签到结果。');renderServerCameraState();
  c.expiry=setInterval(()=>{
    const remaining=Math.max(0,Math.ceil((c.deadline-performance.now())/1000));
    if(sc('remaining'))sc('remaining').textContent=`剩余 ${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')}`;
    if(!remaining){stopServerCamera('本次扫码权限已超时。');c.phase='ended';clearInterval(c.expiry);renderServerCameraState();}
  },250);
  return data;
}
function initializeServerScanLink(){
  serverCamera.capability=true;
  // Credentials are entered in the form, never carried in the address.
  if(location.hash)history.replaceState(null,'',location.pathname);
  showServerScanCodeForm();
}
document.addEventListener('submit',async event=>{
  if(event.target.id!=='scan-code-form')return;
  event.preventDefault();const button=sc('scan-code-submit');if(button.disabled)return;
  button.disabled=true;sc('scan-code-error').textContent='';
  try{await verifyServerScanCode(sc('scan-code').value.trim());sc('scan-code').value='';}
  catch(error){sc('scan-code-error').textContent=error.message;}
  finally{button.disabled=false;}
});
document.addEventListener('click',event=>{
  if(event.target.closest('#scan-code-reenter')){showServerScanCodeForm();sc('scan-code').value='';sc('scan-code-error').textContent='';sc('scan-code')?.focus?.();}
});

document.addEventListener('click',async event=>{
  const button=event.target.closest('#server-camera-start,#server-camera-stop,#server-camera-result');if(!button||button.disabled)return;
  if(button.id==='server-camera-start')void startServerCamera();
  if(button.id==='server-camera-stop'){
    const stopping=serverCamera.runId||serverCamera.capability?scRequest('stop').catch(()=>null):Promise.resolve();
    stopServerCamera('扫描已停止，正在读取结果。',false);
    if(serverCamera.capability){serverCamera.phase='ended';renderServerCameraState();}
    await stopping;void viewServerCameraResult();
  }
  if(button.id==='server-camera-result')void viewServerCameraResult();
});
document.addEventListener('change',event=>{
  if(event.target.id==='server-camera-select-all'){
    const c=serverCamera;
    if(c.busy||c.phase==='running'||(c.capability&&(!c.csrf||c.phase==='ended')))return;
    if(event.target.checked){c.manualUsers=new Set(selectedServerCameraUsers());selectAllServerCameraUsers();}
    else{
      document.querySelectorAll('[name="server-camera-user"]').forEach(input=>{input.checked=!input.disabled&&Boolean(c.manualUsers?.has(input.value));});
      renderServerCameraState();
    }
  }
  if(['server-camera-report-location','server-camera-use-device-location'].includes(event.target.id))renderServerCameraState();
  if(event.target.name==='server-camera-user')renderServerCameraState();
});
document.addEventListener('input',event=>{
  if(event.target.id==='server-camera-zoom'){
    updateServerCameraZoom();QRVision.outline(sc('server-camera-outline'),null);
  }
});
window.addEventListener('pagehide',()=>{
  const c=serverCamera;
  if(c.capability&&c.csrf&&!c.runId&&c.phase!=='ended'){
    void fetch('/scan-api/close',{method:'POST',credentials:'same-origin',keepalive:true,headers:scHeaders(),body:'{}'}).catch(()=>{});
    c.phase='ended';
  }
  stopServerCamera('',true);
});
document.addEventListener('visibilitychange',()=>{
  if(serverCamera.locating&&!serverCamera.runId)return;
  if(serverCamera.native&&serverCamera.busy&&!serverCamera.runId)return; // Android owns the permission-dialog lifecycle.
  if(document.hidden&&(serverCamera.phase==='running'||serverCamera.busy))stopServerCamera('页面已进入后台，手机和服务器扫描已停止。');
});
if(document.querySelector('[data-scan-capability]'))void initializeServerScanLink();
function useDeviceLocation(){return Boolean((window.DevicePosition?.available()||window.AndroidScanner?.deviceLocationAvailable)&&sc('server-camera-report-location')?.checked&&sc('server-camera-use-device-location')?.checked);}
window.onAndroidCapabilities=()=>{renderServerCameraState();if(typeof bulkDraw==='function')bulkDraw();};
