'use strict';
const deviceSourceNames={generated:'自动随机生成',manual:'手动绑定',unified:'统一绑定',browser:'本浏览器标识',imported:'手机分享二维码'};
function deviceSettingsEntry(){
  return `<section class="panel"><div class="panel-header"><div><h3>设备码绑定</h3><p class="subheading">查看所有账户的设备码，逐个绑定或统一设置；未绑定时自动生成并长期沿用。</p></div><a class="button secondary small" href="#devices">管理设备码 →</a></div></section>`;
}
function deviceBindingsPage(){
  return heading('设备码绑定','每个账户固定保存一个设备码，重新登录、扫码和重启后继续沿用。','<a class="button secondary" href="#settings">返回设置</a>')+
    '<div id="devices-content"><section class="panel"><div class="panel-body">正在读取设备码绑定…</div></section></div>';
}
function deviceReaderButtons(){
  return '<div class="actions device-readers"><button class="button secondary small" type="button" data-device-reader>读取本机设备码（浏览器）</button><button class="button secondary small" type="button" data-device-import>读取手机分享二维码</button><input class="hidden" type="file" data-device-file accept="image/png,image/jpeg,image/webp"></div>';
}
function deviceBindingsHTML(data){
  const settings=data.device_settings;
  return `<section class="notice"><b>本机读取说明</b><p>网页不能直接读取 Android OAID / IMEI。“读取本机”读取当前浏览器保存的随机标识，首次使用生成一次，不是手机硬件码；清除浏览器数据后它会重建，已经绑定到账户的码仍保存在服务器。手机实际设备码可从随地大小签的账号分享二维码读取 dc。二维码只在本机解码，仅提取设备码，不上传图片、账号或密码。</p></section>`+
    `<form id="device-global-form" class="panel"><div class="panel-header"><div><h3>统一设备码</h3><p class="subheading">作为新账户的默认码，也可以覆盖现有账户的绑定。</p></div></div><div class="panel-body"><div class="field"><label for="device-global-code">统一设备码（留空停用新账户默认码）</label><textarea id="device-global-code" name="code" class="device-code" rows="2" maxlength="512" autocomplete="off" spellcheck="false">${esc(settings.code)}</textarea></div>${deviceReaderButtons()}<div class="field check-field"><input type="checkbox" id="device-apply-all" name="apply_existing"><label for="device-apply-all">同时覆盖以下所有现有账户的设备码</label></div><p class="setting-note">未勾选时只影响以后新增的账户；清空默认码不会改动已有绑定。账户可随后单独覆盖。设备码从下一次请求开始使用，不修改已发出的请求。</p><p class="inline-error" data-device-error role="alert"></p><p class="setting-note" data-device-status role="status"></p></div><div class="panel-actions"><button class="button primary" type="submit">保存统一设置</button></div></form>`+
    `<section class="panel"><div class="panel-header"><div><h3>账户设备码</h3><p class="subheading">${data.device_bindings.length} 个账户 · 仅管理员可查看完整设备码</p></div><button type="button" class="button secondary small" id="device-refresh">刷新</button></div><div class="panel-body device-account-list">${data.device_bindings.map(a=>`<form class="device-account-form" data-id="${esc(a.id)}"><div class="device-row-title"><h3>${esc(a.name)}</h3><span class="badge purple">${esc(deviceSourceNames[a.source]||a.source)}</span></div><div class="field"><label for="device-code-${esc(a.id)}">当前保存的设备码</label><textarea id="device-code-${esc(a.id)}" name="code" class="device-code" rows="2" maxlength="512" required autocomplete="off" spellcheck="false">${esc(a.code)}</textarea><small>更新于 ${esc(date(a.updated_at))} · 不操作时持续沿用此码</small></div>${deviceReaderButtons()}<div class="actions"><button type="submit" class="button primary small">保存此账户绑定</button><button type="button" class="button secondary small" data-device-random>重新生成随机码并绑定</button></div><p class="inline-error" data-device-error role="alert"></p><p class="setting-note" data-device-status role="status"></p></form>`).join('')||'<p class="muted">请先到用户管理添加超星账户。</p>'}</div></section>`;
}
async function loadDeviceBindings(){
  const root=$('#devices-content');if(!root)return;
  try{const data=await api('/devices');if($('#devices-content')===root)root.innerHTML=deviceBindingsHTML(data);}
  catch(error){if($('#devices-content')===root)root.textContent=error.message;}
}
function updateDeviceBindings(data,root){if($('#devices-content')===root)root.innerHTML=deviceBindingsHTML(data);}
document.addEventListener('input',event=>{if(event.target.matches('.device-code'))event.target.dataset.source='manual';});
document.addEventListener('submit',async event=>{
  const form=event.target;if(form.id!=='device-global-form'&&!form.matches('.device-account-form'))return;
  event.preventDefault();const root=$('#devices-content');
  await busy(form.querySelector('[type="submit"]'),async()=>{
    $('[data-device-error]',form).textContent='';
    try{
      const data=form.id==='device-global-form'?await api('/devices/global','PUT',{code:form.elements.code.value.trim(),apply_existing:form.elements.apply_existing.checked}):
        await api(`/accounts/${encodeURIComponent(form.dataset.id)}/device`,'PUT',{action:'bind',code:form.elements.code.value.trim(),source:form.elements.code.dataset.source||'manual'});
      updateDeviceBindings(data,root);toast('设备码已保存，后续请求沿用此绑定');
    }catch(error){$('[data-device-error]',form).textContent=error.message;}
  });
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-device-reader],[data-device-import],[data-device-random],#device-refresh');if(!button)return;
  if(button.id==='device-refresh'){await loadDeviceBindings();return;}
  const form=button.closest('form'),error=$('[data-device-error]',form),status=$('[data-device-status]',form);error.textContent='';status.textContent='';
  if(button.hasAttribute('data-device-import')){$('[data-device-file]',form).click();return;}
  await busy(button,async()=>{
    try{
      if(button.hasAttribute('data-device-reader')){
        if(!window.isSecureContext||!window.crypto?.getRandomValues)throw new Error('读取本浏览器标识需要 HTTPS 或 localhost。');
        let code;
        try{code=DeviceCodes.localCode(window.localStorage,bytes=>window.crypto.getRandomValues(bytes),value=>btoa(value));}
        catch{throw new Error('本浏览器无法读取或持久保存设备码，请使用手动码或手机分享二维码。');}
        form.elements.code.value=code;form.elements.code.dataset.source='browser';
        status.textContent='已读取当前浏览器标识，点击保存后才绑定到账户。';
      }else{
        const root=$('#devices-content');
        const data=await api(`/accounts/${encodeURIComponent(form.dataset.id)}/device`,'PUT',{action:'random'});
        updateDeviceBindings(data,root);toast('已生成并保存新的随机设备码');
      }
    }catch(reason){error.textContent=reason.message;}
  });
});
document.addEventListener('change',async event=>{
  const input=event.target;if(!input.matches('[data-device-file]'))return;
  const file=input.files?.[0],form=input.closest('form');if(!file)return;
  const error=$('[data-device-error]',form),status=$('[data-device-status]',form);input.disabled=true;error.textContent='';status.textContent='正在本机读取设备码…';
  try{
    const result=await SignQR.decodeImage(file),code=DeviceCodes.fromShare(result.raw);
    if(!form.isConnected)return;
    form.elements.code.value=code;form.elements.code.dataset.source='imported';
    status.textContent='已提取手机二维码中的设备码，点击保存后绑定；未上传图片或其他字段。';
  }catch(reason){error.textContent=reason.message;status.textContent='';}
  finally{input.value='';input.disabled=false;}
});
