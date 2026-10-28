'use strict';
const signVerifications=new Map();
function clearSignVerification(context,cancel=true){
  const current=signVerifications.get(context);signVerifications.delete(context);
  if(current&&cancel&&state.authenticated)api(`/accounts/${encodeURIComponent(current.account)}/verification/${encodeURIComponent(current.value.id)}`,'POST',{action:'cancel'}).catch(()=>{});
  $(`#${context}-verification`)?.replaceChildren();
}
function showSignVerification(context,account,value){
  clearSignVerification(context,false);
  if(!value||!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(value.background)||!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(value.piece))throw new Error('验证图片无效，请重新提交');
  let host=$(`#${context}-verification`);
  if(!host&&context==='sign'){
    host=document.createElement('div');host.id='sign-verification';$('#sign-error').before(host);
  }
  if(!host)return;
  signVerifications.set(context,{account,value});
  host.innerHTML=`<section class="sign-verification"><h3>完成滑块验证</h3><p>将拼图拖到缺口处，再点击“验证并继续”。自动验证未通过时，本步骤不会消耗用户的失败次数。</p><div class="verification-images"><img class="verification-background" src="${value.background}" alt="验证背景图"><img class="verification-piece" src="${value.piece}" alt="可拖动的拼图"></div><input type="range" class="verification-range" min="0" max="${Number(value.width)-Number(value.piece_width)}" value="0" step="1" aria-label="拖动拼图验证" data-context="${context}"><p class="verification-error inline-error" role="alert"></p><div class="actions">${button('验证并继续','verification-check','primary small','',`data-context="${context}"`)}${button('刷新验证图片','verification-refresh','secondary small','',`data-context="${context}"`)}${button('取消验证','verification-cancel','secondary small','',`data-context="${context}"`)}</div></section>`;
  $('.verification-piece',host).style.width=(value.piece_width/value.width*100)+'%';
  $('.actions',host).scrollIntoView({block:'nearest'});
}
document.addEventListener('input',event=>{
  if(!event.target.matches('.verification-range'))return;
  const context=event.target.dataset.context,current=signVerifications.get(context);
  if(current)$('.verification-piece',$(`#${context}-verification`)).style.left=(Number(event.target.value)/current.value.width*100)+'%';
});
document.addEventListener('click',async event=>{
  const target=event.target.closest('[data-action^="verification-"]');if(!target)return;
  const context=target.dataset.context,current=signVerifications.get(context);if(!current)return;
  const host=$(`#${context}-verification`),action=target.dataset.action.slice(13);
  if(action==='cancel'){
    clearSignVerification(context);
    if(context==='camera')closeSignCamera('已取消验证并停止扫码。');
    return;
  }
  await busy(target,async()=>{
    try{
      const payload=action==='refresh'?{action:'refresh'}:{action:'check',x:Number($('.verification-range',host).value)};
      const result=await api(`/accounts/${encodeURIComponent(current.account)}/verification/${encodeURIComponent(current.value.id)}`,'POST',payload);
      if(signVerifications.get(context)!==current)return;
      if(result.verification)showSignVerification(context,current.account,result.verification);
      else if(result.verified){
        clearSignVerification(context,false);
        if(context==='camera'){
          cameraSession.verification=null;cameraSession.proof={id:result.id,account:current.account};
          cameraSession.message='验证已完成，等待最新二维码后继续。';renderCameraStatus();
        }else{
          const form=$('#sign-form');if(form&&$('#modal').open&&form.dataset.account===current.account){form.dataset.verification=result.id;form.requestSubmit();}
        }
      }
    }catch(error){if(signVerifications.get(context)===current)$('.verification-error',host).textContent=error.message;}
  });
});
