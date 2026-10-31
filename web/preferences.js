'use strict';
function preferencesPanel() {
  const value=state.preferences||{account_label:'phone_tail',include_group_sign:false};
  const modes=[['phone_tail','手机尾号 1234'],['surname_mask','姓氏＋星号（张**）'],['full_name','完整姓名（张三丰）'],['masked_surname','星号＋名字（*三丰）'],['surname_tail','姓氏＋尾号（张 1234）']];
  return `<form id="preferences-form" class="panel"><div class="panel-header"><div><h3>用户显示与签到来源</h3><p class="subheading">网页与 QQ 共用，仅改变显示，不修改超星真实姓名或管理员登录名</p></div></div><div class="panel-body"><div class="field"><label for="account-label-mode">超星用户显示方式</label><select id="account-label-mode" name="account_label">${modes.map(([key,label])=>`<option value="${key}" ${key===value.account_label?'selected':''}>${label}</option>`).join('')}</select><small>复姓保留完整姓氏；按实际字数用星号补位。没有手机号时，尾号模式明确回退到 UID 尾号。</small></div><div class="field check-field"><input type="checkbox" id="include-group-sign" name="include_group_sign" ${value.include_group_sign?'checked':''}><label for="include-group-sign">获取超星群聊签到</label></div><p class="setting-note">开启后网页增加“群聊签到”分页，QQ 活动列表合并课程与群聊签到并标注来源。群聊消息服务与课程活动接口独立，读取失败会明确提示，不会当成“没有签到”。不读取 QQ 群消息。</p><p class="inline-error" id="preferences-error" role="alert"></p></div><div class="panel-actions"><button class="button primary" type="submit">保存显示与签到设置</button></div></form>`;
}
function cameraPreferencesPanel() {
  const value=state.preferences||{};
  return `<form id="camera-preferences-form" class="panel"><div class="panel-header"><div><h3>扫码签到</h3><p class="subheading">保存后在下一次启动扫码时生效</p></div></div><div class="panel-body"><div class="field-grid"><div class="field"><label for="camera-concurrency">扫码签到并发数</label><input id="camera-concurrency" name="camera_concurrency" type="number" min="1" max="5" step="1" value="${esc(value.camera_concurrency??1)}" required><small>默认 1，范围 1～5；表示同一队列最多同时提交的用户数。</small></div><div class="field"><label for="camera-scan-interval">两次识别间隔（秒）</label><input id="camera-scan-interval" name="camera_scan_interval" type="number" min="0.05" max="10" step="0.05" value="${esc(value.camera_scan_interval??0.1)}" required><small>默认 0.1 秒，范围 0.05～10 秒；上一帧未识别完时等待，不叠加解码。</small></div></div><p class="setting-note">同一用户保持串行，失败后至少等待 2.5 秒再重试。需要滑块、位置或本人照片时，等待当前批次返回后逐人处理。并发提交不保证同时成功。</p><p id="camera-preferences-error" class="inline-error" role="alert"></p></div><div class="panel-actions"><button class="button primary" type="submit">保存扫码设置</button></div></form>`;
}
document.addEventListener('submit',async event=>{
  if(event.target.id==='camera-preferences-form'){
    event.preventDefault();const form=event.target;
    await busy(form.querySelector('[type="submit"]'),async()=>{
      try{
        const data=await api('/preferences','PUT',{camera_concurrency:Number(form.elements.camera_concurrency.value),camera_scan_interval:Number(form.elements.camera_scan_interval.value)});
        state.preferences=data.preferences;toast('扫码设置已保存，下次启动扫码时生效');
      }catch(error){$('#camera-preferences-error').textContent=error.message;throw error;}
    });
    return;
  }
  if(event.target.id!=='preferences-form')return;
  event.preventDefault();const form=event.target;
  await busy(form.querySelector('[type="submit"]'),async()=>{
    try {const data=await api('/preferences','PUT',{account_label:form.elements.account_label.value,include_group_sign:form.elements.include_group_sign.checked});Object.assign(state,data);state.activities={};state.signWarnings={};render();toast('显示与签到设置已保存，QQ 重新发送“签到”即可使用');}
    catch(error) {$('#preferences-error').textContent=error.message;throw error;}
  });
});
