'use strict';
const faceCapture={generation:0,target:null,stream:null,image:'',uploading:false};
const signAction=value=>value?.phase==='out'?'签退':'签到';

function stopFaceCamera(){
  faceCapture.stream?.getTracks().forEach(track=>track.stop());faceCapture.stream=null;
  const video=$('#face-camera-video');if(video){video.pause();video.srcObject=null;video.classList.add('hidden');}
}
function closeSignFace(context){
  if(context&&faceCapture.target?.context!==context)return;
  faceCapture.generation++;stopFaceCamera();faceCapture.target=null;faceCapture.image='';
  const dialog=$('#face-dialog');if(dialog?.open)dialog.close();
  $('#face-photo-preview')?.removeAttribute('src');
}
function showSignFace(context,account,activity,source){
  if(faceCapture.uploading){toast('上一照片请求仍在返回结果，请稍候再试。',true);return;}
  closeSignFace();
  if(context==='camera')suspendCameraForFace();
  faceCapture.target={context,account,activity,source};
  const name=state.accounts.find(a=>a.id===account)?.name||'当前用户';
  $('#face-dialog').innerHTML=`<div class="modal-head"><h2>本人照片 · ${esc(name)}</h2><button type="button" class="icon-button" data-action="face-close" aria-label="关闭人脸照片窗口">×</button></div><div class="modal-body"><p class="setting-note">仅为当前用户、当前活动准备本人照片。照片将发送至该超星账号的云盘和验证接口；平台可能保留副本，本机不落盘。照片采集不代表活体已通过，最终以平台结果为准。</p><div class="face-preview"><video id="face-camera-video" class="hidden" autoplay muted playsinline aria-label="本人照片摄像头预览"></video><img id="face-photo-preview" class="hidden" alt="本次本人照片预览"><p>开启前置摄像头拍摄，或在手机上选择当前本人照片。</p></div><div class="face-capture-controls">${button('开启前置摄像头','face-start','secondary small')}${button('拍摄当前照片','face-snap','secondary small')}${button('选择当前照片','face-file','secondary small')}<input id="face-image-file" type="file" class="hidden" accept="image/jpeg,image/png,image/webp" capture="user"></div><label class="face-consent"><input id="face-consent" type="checkbox"><span>确认为当前所选用户本人照片，并同意发送到超星用于本次验证；不保存为其他用户的可复用照片。</span></label><p id="face-error" class="inline-error" role="alert"></p></div><div class="modal-actions"><button type="button" class="button secondary" data-action="face-close">取消</button><button type="button" class="button primary" data-action="face-upload">上传照片并继续</button></div>`;
  $('#face-dialog').showModal();
  const generation=faceCapture.generation;
  api(`/accounts/${encodeURIComponent(account)}/activities/${encodeURIComponent(activity)}/requirements?source=${source}`).then(data=>{
    if(generation!==faceCapture.generation)return;
    const url=new URL(data.requirements.official_url);
    if(url.origin!=='https://mobilelearn.chaoxing.com')return;
    const link=document.createElement('a');link.className='button secondary small';link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent='在官方页面完成验证';
    $('.face-capture-controls').append(link);
  }).catch(()=>{});
}
async function startFaceCamera(){
  if(!faceCapture.target||faceCapture.uploading)return;
  $('#face-error').textContent='';
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){$('#face-error').textContent='实时摄像头需要 HTTPS / localhost；也可用“选择当前照片”在手机上拍摄。';return;}
  const generation=++faceCapture.generation;stopFaceCamera();
  try{
    const stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:'user'},width:{ideal:1024},height:{ideal:1024}}});
    if(generation!==faceCapture.generation){stream.getTracks().forEach(t=>t.stop());return;}
    faceCapture.stream=stream;const video=$('#face-camera-video');video.srcObject=stream;await video.play();
    if(generation!==faceCapture.generation)return;
    video.classList.remove('hidden');$('#face-photo-preview').classList.add('hidden');$('.face-preview p').classList.add('hidden');
  }catch{if(generation===faceCapture.generation)$('#face-error').textContent='无法开启摄像头，请检查权限或使用当前照片入口。';}
}
function prepareFacePhoto(source,width,height){
  if(!faceCapture.target)throw new Error('拍摄窗口已关闭');
  if(!width||!height||width*height>24000000)throw new Error('照片尺寸无效或过大，请重新拍摄');
  const scale=Math.min(1,1024/Math.max(width,height)),canvas=document.createElement('canvas');
  canvas.width=Math.round(width*scale);canvas.height=Math.round(height*scale);
  const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(source,0,0,canvas.width,canvas.height);
  let image='';for(const quality of [0.85,0.7,0.5,0.35]){image=canvas.toDataURL('image/jpeg',quality);if(image.length<=800000)break;}
  if(image.length>800000)throw new Error('照片过大，请重新拍摄或裁剪');
  faceCapture.image=image;stopFaceCamera();const preview=$('#face-photo-preview');preview.src=image;preview.classList.remove('hidden');$('.face-preview p').classList.add('hidden');
}
async function uploadFacePhoto(){
  const c=faceCapture,target=c.target;if(!target||c.uploading)return;
  if(!c.image){$('#face-error').textContent='请先拍摄或选择本人照片。';return;}
  if(!$('#face-consent').checked){$('#face-error').textContent='请先确认当前用户与照片发送用途。';return;}
  c.uploading=true;const generation=c.generation;const button=$('[data-action="face-upload"]');button.disabled=true;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),120000);
  try{
    const result=await api(`/accounts/${encodeURIComponent(target.account)}/face`,'POST',{activity_id:target.activity,source:target.source,image:c.image,consent:true},{signal:controller.signal});
    if(generation!==c.generation){if(state.authenticated)api(`/accounts/${encodeURIComponent(target.account)}/face/${encodeURIComponent(result.face_id)}/cancel`,'POST',{}).catch(()=>{});return;}
    closeSignFace();
    if(target.context==='camera'&&cameraSession.queue?.activityId===target.activity&&cameraSession.queue?.current?.id===target.account){
      cameraSession.faceProof={id:result.face_id,account:target.account};cameraSession.requirement=null;
      cameraSession.message=cameraSession.facePaused?'照片已提交，点击“处理后继续重试”恢复扫码，等待平台最终确认。':'照片已提交，等待当前二维码和平台最终确认。';renderCameraStatus();
    }else{
      const form=$('#sign-form');if(form&&$('#modal').open&&form.dataset.account===target.account&&form.dataset.activity===target.activity){form.dataset.face=result.face_id;form.requestSubmit();}
    }
  }catch(error){if(generation===c.generation)$('#face-error').textContent=error.name==='AbortError'?'照片请求超时，平台可能已收到照片；请先核对结果后再重试。':error.message;}
  finally{clearTimeout(timer);c.uploading=false;if(button.isConnected)button.disabled=false;}
}

async function loadSignRequirements(form){
  const account=form.dataset.account,id=form.dataset.activity,source=form.dataset.source;
  try{
    const data=await api(`/accounts/${encodeURIComponent(account)}/activities/${encodeURIComponent(id)}/requirements?source=${source}`);
    if(!$('#modal').open||$('#sign-form')!==form)return;
    const r=data.requirements,host=$('#sign-requirements');form.dataset.phase=r.phase;form.dataset.requiresLocation=r.needs_location?'1':'0';applyRequiredSignLocation(form);
    const selected=state.activities[signActivityKey(account,source)]?.find(a=>a.id===id);if(selected)selected.phase=r.phase;
    $('button[type="submit"]',form).textContent='确认提交'+signAction(r);
    host.innerHTML=`<b>${r.phase==='out'?'当前为签退活动':'当前为签到活动'}</b><p>${[r.needs_face?'需要本人照片验证':'',r.needs_location?'要求位置，沿用已有点位 / 地图方案':'',r.needs_captcha?'可能需要滑块验证':''].filter(Boolean).map(esc).join(' · ')||'按活动要求填写后提交。'}</p><div class="actions">${r.sign_in_id?button('查看关联签到','sign-related','secondary small','',`data-relation="in"`):''}${r.sign_out_id?button('查看关联签退','sign-related','secondary small','',`data-relation="out"`):''}${r.needs_face?button('准备本人照片','sign-face','secondary small'):''}${button('已在官方完成，核对结果','sign-confirm','secondary small')}<a class="button secondary small" href="${esc(r.official_url)}" target="_blank" rel="noopener noreferrer">在官方页面处理</a></div>${r.sign_out_publish_at&&!r.sign_out_id?'<p>签退尚未发布，发布后刷新活动列表。</p>':''}`;
  }catch(error){if($('#sign-form')===form)$('#sign-requirements').textContent='要求读取失败：'+error.message;}
}
function applyRequiredSignLocation(form){
  if(!form)return;
  if(form.dataset.requiresLocation==='1'&&form.elements.kind.value==='qr'){
    if(!$('#sign-extra-location',form)){const box=document.createElement('div');box.id='sign-extra-location';box.innerHTML='<h3>本次二维码同时要求位置</h3>'+signFields('location');$('#sign-fields',form).after(box);}
  }else $('#sign-extra-location',form)?.remove();
}
async function confirmSignResult(account,activity,source,context){
  const queue=context==='camera'?cameraSession.queue:null;
  const result=await api(`/accounts/${encodeURIComponent(account)}/activities/${encodeURIComponent(activity)}/confirm`,'POST',{source});
  if(context==='camera'&&queue===cameraSession.queue&&queue?.activityId===activity){
    if(result.signed&&queue.current?.id===account&&queue.confirm(account,result.message))cameraAccountFinished(account);
    if(!cameraSession.busy)activateCameraAttention();
    cameraSession.message=result.message;if(cameraSession.queue?.done)closeSignCamera('所选用户已全部完成。');renderCameraStatus();
  }else if(context!=='camera'&&result.signed){
    const item=state.activities[signActivityKey(account,source)]?.find(a=>a.id===activity);if(item)item.signed=true;
    $('#modal').close();render();
  }
  toast(result.message,!result.signed);
  return result;
}
document.addEventListener('click',async event=>{
  const target=event.target.closest('[data-action]');if(!target)return;
  const action=target.dataset.action;
  if(action==='face-close')return closeSignFace();
  if(action.startsWith('face-')&&faceCapture.uploading)return;
  if(action==='face-start')return startFaceCamera();
  if(action==='face-file')return $('#face-image-file').click();
  if(action==='face-snap'){try{const video=$('#face-camera-video');prepareFacePhoto(video,video.videoWidth,video.videoHeight);}catch(error){$('#face-error').textContent=error.message;}return;}
  if(action==='face-upload')return uploadFacePhoto();
  const form=$('#sign-form');
  if(action==='sign-face'&&form)return showSignFace('sign',form.dataset.account,form.dataset.activity,form.dataset.source);
  if(action==='sign-confirm'&&form)return busy(target,()=>confirmSignResult(form.dataset.account,form.dataset.activity,form.dataset.source,'sign'));
  if(action==='sign-related'&&form)return busy(target,async()=>{
    const data=await api(`/accounts/${form.dataset.account}/activities/${form.dataset.activity}/related`,'POST',{source:form.dataset.source,relation:target.dataset.relation});
    if($('#sign-form')!==form)return;
    const list=state.activities[signActivityKey(form.dataset.account,form.dataset.source)]||[];
    if(!list.some(a=>a.id===data.activity.id))list.push(data.activity);
    openSign(data.activity.id);
  });
});
document.addEventListener('change',async event=>{
  if(event.target.id!=='face-image-file')return;
  const file=event.target.files[0],generation=faceCapture.generation;event.target.value='';if(!file)return;
  try{
    if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8*1024*1024)throw new Error('请选择 8 MB 以内的照片');
    const image=await createImageBitmap(file);try{if(generation===faceCapture.generation)prepareFacePhoto(image,image.width,image.height);}finally{image.close();}
  }catch(error){if(generation===faceCapture.generation)$('#face-error').textContent=error.message;}
});
window.addEventListener('pagehide',()=>closeSignFace());
window.addEventListener('hashchange',()=>closeSignFace());
document.addEventListener('visibilitychange',()=>{if(document.hidden)closeSignFace();});
document.addEventListener('DOMContentLoaded',()=>$('#face-dialog').addEventListener('cancel',()=>closeSignFace()));
