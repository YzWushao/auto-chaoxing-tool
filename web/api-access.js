'use strict';
function apiAccessPanel(){
  return '<section class="panel api-access"><div class="panel-header"><div><h3>开放 API · 机器人插件</h3><p class="subheading">使用独立密钥执行网页操作，支持 OpenAPI 与模型工具定义</p></div><button type="button" class="button secondary" id="api-access-refresh">刷新</button></div><div class="panel-body" id="api-access-content">正在读取 API 设置…</div></section>';
}
function apiKeyTime(stamp){return stamp?new Date(stamp*1000).toLocaleString('zh-CN'):'尚未使用';}
function apiAccessContent(data){
  const keys=data.keys.map(key=>{
    const expired=key.expires_at*1000<=Date.now(),status=key.revoked?'已撤销':expired?'已过期':'可用';
    return `<article class="api-key-row"><div><strong>${esc(key.name)}</strong><span class="badge">${status}</span></div><p><code>${esc(key.prefix)}…</code> · ${esc(key.scopes.join(' / '))}</p><p class="setting-note">过期：${esc(apiKeyTime(key.expires_at))} · 最近使用：${esc(apiKeyTime(key.last_used_at))} · ${key.rate_limit} 次/分钟</p><button type="button" class="button secondary small" data-api-revoke="${esc(key.id)}" ${key.revoked?'disabled':''}>撤销密钥</button></article>`;
  }).join('')||'<p class="setting-note">尚未创建密钥。</p>';
  const audit=data.audit.map(row=>`<tr><td>${esc(apiKeyTime(row.created_at))}</td><td>${esc(row.key_name||'已移除')}</td><td><code>${esc(row.operation)}</code></td><td>${row.status}</td><td>${row.duration_ms} ms</td><td><code>${esc(row.request_id)}</code></td></tr>`).join('');
  return `<form id="api-access-toggle"><label class="camera-switch"><input type="checkbox" role="switch" name="enabled" ${data.enabled?'checked':''}>启用开放 API（默认关闭）</label><button type="submit" class="button secondary">保存开关</button></form>
    <p class="setting-note">插件地址：当前网站根地址 + <code>/api/v1</code>。请求头使用 <code>Authorization: Bearer &lt;API Key&gt;</code>；API 不需要网页登录或 CSRF。关闭开关会立即阻止所有密钥调用，重新开启可继续使用未撤销密钥。</p>
    <p class="api-doc-links"><a href="/api/access/openapi.json" download="auto-chaoxing-openapi.json">下载 OpenAPI 文档</a><a href="/api/access/tools" download="auto-chaoxing-tools.json">下载模型工具定义</a></p>
    <form id="api-key-create"><h4>新建插件密钥</h4><div class="field-grid"><div class="field"><label for="api-key-name">密钥名称</label><input id="api-key-name" name="name" required maxlength="64" placeholder="例如 QQ 签到插件" autocomplete="off"></div><div class="field"><label for="api-key-days">有效天数</label><input id="api-key-days" name="expires_days" type="number" value="90" min="1" max="365" required></div><div class="field"><label for="api-key-rate">每分钟请求上限</label><input id="api-key-rate" name="rate_limit" type="number" value="600" min="10" max="6000" required></div></div>
    <fieldset class="api-scope-list"><legend>可调用的操作</legend>${Object.entries(data.scopes).map(([key,label])=>`<label><input type="checkbox" name="scopes" value="${esc(key)}" ${['read','sign:write'].includes(key)?'checked':''}><span><code>${esc(key)}</code> · ${esc(label)}</span></label>`).join('')}</fieldset>
    <p class="setting-note">默认只选读取和签到。按插件需要授权；密钥可操作管理范围内的全部超星用户。管理员改名或改密会撤销全部 API 密钥。密钥只交给插件的 HTTP 客户端，不放入模型提示词、QQ 回复或公共仓库。</p><button type="submit" class="button primary">创建密钥</button></form>
    <section id="api-key-created" hidden role="status"><h4>请立即复制，新密钥只显示这一次</h4><div class="field"><label for="api-key-secret">API Key</label><input id="api-key-secret" readonly autocomplete="off" spellcheck="false"></div><div class="actions"><button type="button" class="button secondary" id="api-key-copy">复制密钥</button><button type="button" class="button secondary" id="api-key-hide">隐藏</button></div></section>
    <p id="api-access-error" class="inline-error" role="alert"></p><h4>已有密钥</h4><div>${keys}</div>
    <details><summary>最近 100 条 API 调用记录</summary><p class="setting-note">仅记录密钥名称、操作、状态、时间与请求编号；不记录请求体、验证码、密码、图片或模型原文。</p><div class="api-audit"><table><thead><tr><th>时间</th><th>密钥</th><th>操作</th><th>状态</th><th>耗时</th><th>请求编号</th></tr></thead><tbody>${audit||'<tr><td colspan="6">暂无调用</td></tr>'}</tbody></table></div></details>`;
}
async function loadApiAccess(){
  const host=$('#api-access-content');if(!host)return;
  try{const data=await api('/access');if(host!==$('#api-access-content'))return;host.innerHTML=apiAccessContent(data);}
  catch(error){if(host===$('#api-access-content'))host.textContent=error.message;}
}
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['api-access-toggle','api-key-create'].includes(form.id))return;
  event.preventDefault();await busy(form.querySelector('[type="submit"]'),async()=>{
    $('#api-access-error').textContent='';
    try{
      if(form.id==='api-access-toggle'){
        await api('/access','PUT',{enabled:form.elements.enabled.checked});toast('API 开关已保存');
      }else{
        const data=await api('/access/keys','POST',{name:form.elements.name.value,expires_days:Number(form.elements.expires_days.value),rate_limit:Number(form.elements.rate_limit.value),scopes:[...form.querySelectorAll('[name="scopes"]:checked')].map(el=>el.value)});
        await loadApiAccess();const input=$('#api-key-secret');if(!input)return;
        input.value=data.token;$('#api-key-created').hidden=false;input.focus();input.select();
      }
    }catch(error){if($('#api-access-error'))$('#api-access-error').textContent=error.message;}
  });
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('#api-access-refresh,#api-key-copy,#api-key-hide,[data-api-revoke]');if(!button)return;
  if(button.id==='api-key-hide'){$('#api-key-secret').value='';$('#api-key-created').hidden=true;return;}
  await busy(button,async()=>{
    if(button.id==='api-access-refresh'){await loadApiAccess();return;}
    if(button.id==='api-key-copy'){
      try{await navigator.clipboard.writeText($('#api-key-secret').value);toast('密钥已复制');}
      catch{$('#api-key-secret').focus();$('#api-key-secret').select();toast('请手动复制已选中的密钥');}return;
    }
    await api('/access/keys/'+encodeURIComponent(button.dataset.apiRevoke),'DELETE',{});await loadApiAccess();toast('密钥已撤销');
  });
});
