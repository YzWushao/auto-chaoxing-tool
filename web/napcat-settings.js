'use strict';
function napcatIntentFields(value) {
  return `<div class="panel-header"><div><h3>QQ 回复 · 模型意图识别</h3><p class="subheading">把口语回复匹配为当前会话中的操作；独立于刷课 API 配置</p></div></div>
  <div class="field check-field"><input type="checkbox" id="napcat-intent-enabled" name="intent_enabled" ${value.intent_enabled?'checked':''}><label for="napcat-intent-enabled">模型介入（默认关闭）</label></div>
  <fieldset id="napcat-intent-fields" ${value.intent_enabled?'':'disabled'}><div class="field-grid">
  <div class="field"><label for="napcat-intent-url">模型 API 地址</label><input id="napcat-intent-url" name="intent_api_url" value="${esc(value.intent_api_url||'')}" placeholder="https://你的 API 服务/v1" autocomplete="off"><small>兼容 Chat Completions。支持根地址、版本路径或完整 /chat/completions；根地址自动补 /v1/chat/completions。公网建议 HTTPS。</small></div>
  <div class="field"><label for="napcat-intent-key">模型 API Key</label><input type="password" id="napcat-intent-key" name="intent_api_key" value="${esc(value.intent_api_key||'')}" autocomplete="off"><small>加密保存在服务器；圆点表示保留已有值，清空后保存可删除。</small></div>
  <div class="field"><label for="napcat-intent-model">模型名称</label><input id="napcat-intent-model" name="intent_model" value="${esc(value.intent_model||'')}" placeholder="填写服务商提供的模型 ID" autocomplete="off"><small>请选择支持 JSON 输出的文本模型。</small></div></div>
  <button type="button" class="button secondary" id="napcat-intent-test">测试模型（不执行签到）</button></fieldset>
  <p class="setting-note">开启后，无法直接匹配标准指令的纯文字回复及当前页的显示标签会发送到你配置的模型服务（可能产生 API 费用）；不发送账户凭据、QQ 号、坐标、二维码或图片。按当前用户显示设置提供标签，手机号仅保留尾号。支持如“第一个和第三个”“下一页看看”；模型只能选择当前页，序号指令仍可跨页。口语全选需要回复“确认全选”，标准“全选”直接执行。接口失败或意图不明不会执行操作。关闭后完全使用原有指令，不调用模型。</p>`;
}
function napcatPanel() {
  const value=state.napcat_settings||{enabled:false,ws_url:'',token:'',allowed_qqs:[]},status=state.napcat_status||{message:'未启用'};
  return `<form id="napcat-settings-form" class="panel"><div class="panel-header"><div><h3>QQ 签到 · NapCat</h3><p class="subheading">私聊发送“签到” → 为谁签到 → 选择活动 → 普通 / 二维码 / 预设位置签到</p></div><span class="badge ${status.state==='connected'?'green':'purple'}" id="napcat-status">${esc(status.message)}</span></div><div class="panel-body"><div class="field-grid"><div class="field"><label for="napcat-url">正向 WebSocket 地址</label><input id="napcat-url" name="ws_url" value="${esc(value.ws_url)}" placeholder="ws://NAS 的 P2P IP:6998/" autocomplete="off"><small>不是 WebUI 管理页。优先使用 P2P 私网；公网请配置 WSS。</small></div><div class="field"><label for="napcat-token">OneBot Token</label><input id="napcat-token" name="token" type="password" value="${esc(value.token)}" autocomplete="off"><small>独立于 WebUI 密码，加密保存；圆点表示保留已有值。</small></div><div class="field"><label for="napcat-qqs">授权 QQ 号（每行一个）</label><textarea id="napcat-qqs" name="allowed_qqs" rows="3" placeholder="填写允许操作的 QQ 号">${esc(value.allowed_qqs.join('\n'))}</textarea><small>只有这些 QQ 的私聊指令有效。授权 QQ 可以选择本控制台管理的所有超星用户，不固定绑定账户。QQ 群消息不处理。</small></div><div class="field"><label for="napcat-scan-base">一次性扫码入口 · 网页根地址</label><input id="napcat-scan-base" name="scan_base_url" value="${esc(value.scan_base_url||'')}" placeholder="https://你的项目域名:端口" autocomplete="off"><small>填写本项目可访问的 HTTPS 根地址（含端口，不带路径）；留空则不发送扫码链接。入口 5 分钟有效，只能领取一次，完成一个活动或主动结束后失效；仅可为 QQ 所选用户扫码，不授予控制台权限。</small></div><div class="field check-field"><input type="checkbox" id="napcat-enabled" name="enabled" ${value.enabled?'checked':''}><label for="napcat-enabled">启用 QQ 签到会话</label></div></div>${napcatIntentFields(value)}<p class="setting-note">收到“签到”始终先询问为谁签到；选择用户后实时刷新活动。普通签到选中即提交；二维码支持上传单张图片，也可通过一次性入口开启摄像头扫码；位置签到列出现有预设点位，选择序号即提交。请只选择本人实际所在位置，不用于伪造出勤。支持“取消”、翻页和 5 分钟未操作过期；断线自动重连，重复消息不重复执行。二维码参数错误或过期由平台反馈。不支持 QQ 群消息、手势、签到码、拍照、刷课控制或主动状态推送。</p><p class="inline-error" role="alert" id="napcat-error"></p><p class="setting-note" role="status" id="napcat-test-result"></p></div><div class="panel-actions"><button type="button" class="button secondary" id="napcat-test">测试连接（不发消息）</button><button type="button" class="button secondary" id="napcat-refresh">刷新连接状态</button><button type="submit" class="button primary">保存并应用</button></div></form>`;
}
function readNapCat(form) {
  return {ws_url:form.elements.ws_url.value.trim(),token:form.elements.token.value,scan_base_url:form.elements.scan_base_url.value.trim(),enabled:form.elements.enabled.checked,allowed_qqs:form.elements.allowed_qqs.value.split(/[\s,，]+/).filter(Boolean),intent_enabled:form.elements.intent_enabled.checked,intent_api_url:form.elements.intent_api_url.value.trim(),intent_api_key:form.elements.intent_api_key.value,intent_model:form.elements.intent_model.value.trim()};
}
document.addEventListener('change',event=>{
  if(event.target.id==='napcat-intent-enabled') $('#napcat-intent-fields').disabled=!event.target.checked;
});
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
  const button=event.target.closest('#napcat-test,#napcat-refresh,#napcat-intent-test');if(!button)return;
  await busy(button,async()=>{
    $('#napcat-error').textContent='';
    try {
      if(button.id==='napcat-intent-test') {const data=await api('/napcat/intent/test','POST',readNapCat(button.closest('form')));$('#napcat-test-result').textContent=data.message;}
      else if(button.id==='napcat-test') {const data=await api('/napcat/test','POST',readNapCat(button.closest('form')));$('#napcat-test-result').textContent=data.message+(data.bot_qq?' · 机器人 QQ '+data.bot_qq:'');}
      else {const data=await api('/napcat/settings');state.napcat_status=data.napcat_status;$('#napcat-status').textContent=data.napcat_status.message;}
    } catch(error) {$('#napcat-error').textContent=error.message;throw error;}
  });
});
