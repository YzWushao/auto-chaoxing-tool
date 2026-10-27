'use strict';
function napcatPanel() {
  const value=state.napcat_settings||{enabled:false,ws_url:'',token:'',allowed_qqs:[]},status=state.napcat_status||{message:'未启用'};
  return `<form id="napcat-settings-form" class="panel"><div class="panel-header"><div><h3>QQ 签到 · NapCat</h3><p class="subheading">私聊发送“签到” → 为谁签到 → 选择活动 → 普通 / 二维码 / 预设位置签到</p></div><span class="badge ${status.state==='connected'?'green':'purple'}" id="napcat-status">${esc(status.message)}</span></div><div class="panel-body"><div class="field-grid"><div class="field"><label for="napcat-url">正向 WebSocket 地址</label><input id="napcat-url" name="ws_url" value="${esc(value.ws_url)}" placeholder="ws://NAS 的 P2P IP:6998/" autocomplete="off"><small>不是 WebUI 管理页。优先使用 P2P 私网；公网请配置 WSS。</small></div><div class="field"><label for="napcat-token">OneBot Token</label><input id="napcat-token" name="token" type="password" value="${esc(value.token)}" autocomplete="off"><small>独立于 WebUI 密码，加密保存；圆点表示保留已有值。</small></div><div class="field"><label for="napcat-qqs">授权 QQ 号（每行一个）</label><textarea id="napcat-qqs" name="allowed_qqs" rows="3" placeholder="填写允许操作的 QQ 号">${esc(value.allowed_qqs.join('\n'))}</textarea><small>只有这些 QQ 的私聊指令有效。授权 QQ 可以选择本控制台管理的所有超星用户，不固定绑定账户。QQ 群消息不处理。</small></div><div class="field check-field"><input type="checkbox" id="napcat-enabled" name="enabled" ${value.enabled?'checked':''}><label for="napcat-enabled">启用 QQ 签到会话</label></div></div><p class="setting-note">收到“签到”始终先询问为谁签到；选择用户后实时刷新活动。普通签到选中即提交；二维码等待单张图片，本地解码后提交；位置签到列出现有预设点位，选择序号即提交。请只选择本人实际所在位置，不用于伪造出勤。支持“取消”、翻页和 5 分钟未操作过期；断线自动重连，重复消息不重复执行。二维码参数错误或过期由平台反馈。不支持 QQ 群消息、手势、签到码、拍照、刷课控制或主动状态推送。</p><p class="inline-error" role="alert" id="napcat-error"></p><p class="setting-note" role="status" id="napcat-test-result"></p></div><div class="panel-actions"><button type="button" class="button secondary" id="napcat-test">测试连接（不发消息）</button><button type="button" class="button secondary" id="napcat-refresh">刷新连接状态</button><button type="submit" class="button primary">保存并应用</button></div></form>`;
}
function readNapCat(form) {
  return {ws_url:form.elements.ws_url.value.trim(),token:form.elements.token.value,enabled:form.elements.enabled.checked,allowed_qqs:form.elements.allowed_qqs.value.split(/[\s,，]+/).filter(Boolean)};
}
document.addEventListener('submit',async event=>{
  if(event.target.id!=='napcat-settings-form') return;
  event.preventDefault();const form=event.target;
  await busy(form.querySelector('[type="submit"]'),async()=>{
    $('#napcat-error').textContent='';
    try {const data=await api('/napcat/settings','PUT',readNapCat(form));Object.assign(state,data);render();toast('NapCat 配置已保存，正在应用');}
    catch(error) {$('#napcat-error').textContent=error.message;throw error;}
  });
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('#napcat-test,#napcat-refresh');if(!button)return;
  await busy(button,async()=>{
    $('#napcat-error').textContent='';
    try {
      if(button.id==='napcat-test') {const data=await api('/napcat/test','POST',readNapCat(button.closest('form')));$('#napcat-test-result').textContent=data.message+(data.bot_qq?' · 机器人 QQ '+data.bot_qq:'');}
      else {const data=await api('/napcat/settings');state.napcat_status=data.napcat_status;$('#napcat-status').textContent=data.napcat_status.message;}
    } catch(error) {$('#napcat-error').textContent=error.message;throw error;}
  });
});
