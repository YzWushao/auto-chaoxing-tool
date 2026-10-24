'use strict';
function mapSettingsPanel() {
  const value=state.map_settings||{provider:'osm',key:'',security_code:'',configured:false};
  return `<form class="panel" id="map-settings-form"><div class="panel-header"><div><h3>地图服务</h3><p class="subheading">默认无需 Key 的免费地图；高德地图为可选服务</p></div><span class="badge purple">${value.configured?'高德已配置':'高德未配置'}</span></div><div class="panel-body"><div class="field-grid"><div class="field"><label for="map-provider-default">默认地图</label><select id="map-provider-default" name="provider"><option value="osm" ${value.provider==='osm'?'selected':''}>免费地图 OpenStreetMap（无需 Key）</option><option value="amap" ${value.provider==='amap'?'selected':''}>高德地图（需自备 Key）</option></select></div><div class="field"><label for="amap-key">高德 Web 端（JS API）Key</label><input id="amap-key" name="key" type="password" autocomplete="off" value="${esc(value.key)}" placeholder="可选；不是 Web 服务类型 Key"></div><div class="field"><label for="amap-security-code">高德安全密钥 securityJsCode</label><input id="amap-security-code" name="security_code" type="password" autocomplete="off" value="${esc(value.security_code)}" placeholder="与上面的 Key 配套"></div></div><p class="setting-note">密钥加密保存在本机，不写入源码 / JSON 点位配置；安全密钥仅由后端代理使用，不发给浏览器。高德 JS Key 按官方机制会在 SDK 请求中使用。圆点表示保留已有内容，同时清空两个密钥可移除。切换不改写已有点位。</p><details><summary>高德 Key 申请流程</summary><ol><li>登录 <a href="https://console.amap.com/" target="_blank" rel="noopener noreferrer">高德开放平台控制台</a>，按提示完成开发者注册 / 认证。</li><li>进入“应用管理 → 我的应用”，创建应用，例如 auto-chaoxing-tool。</li><li>添加 Key，平台选择“Web 端（JS API）”，不是“Web 服务”。</li><li>复制 Key 和配套 securityJsCode，按控制台要求设置使用站点的白名单（本机访问使用 127.0.0.1 或 localhost，按平台实际格式填写）。</li><li>填入本页并保存，然后在选点窗口切换高德。额度、认证和使用许可按高德当前控制台为准，不保证永久免费。</li></ol><a href="https://lbs.amap.com/api/javascript-api-v2/prerequisites" target="_blank" rel="noopener noreferrer">官方申请说明 ↗</a></details><p id="map-settings-error" class="inline-error" role="alert"></p></div><div class="panel-actions"><button type="submit" class="button primary">保存地图设置</button></div></form>`;
}
function mapProviderHTML(context) {
  return `<div class="field map-provider-field"><label for="${context}-map-provider">地图来源</label><select id="${context}-map-provider" data-map-provider="${context}"><option value="osm" ${(state.map_settings?.provider||'osm')==='osm'?'selected':''}>免费地图（无需 Key）</option><option value="amap" ${state.map_settings?.provider==='amap'?'selected':''}>高德地图（需配置 Key）</option></select></div>`;
}
function mountMapPicker(context,provider) {
  const isPreset=context==='preset',container=$(isPreset?'#preset-map-canvas':'#sign-map-canvas');
  const options={onSelect:isPreset?fillPresetMap:fillSignMap,onStatus:isPreset?presetMapStatus:signMapStatus};
  if(provider==='amap') return AMapPicker.mount(container,{...options,convert:SignMap});
  const picker=SignMap.mount(container,{L:window.L,...options});picker.provider='osm';return picker;
}
function switchMapProvider(context,provider) {
  const value=state[context+'MapPoint'];stopMapSearch(context);state[context+'Map']?.destroy();
  state[context+'Map']=null;
  try {state[context+'Map']=mountMapPicker(context,provider);if(value) state[context+'Map'].center(value);}
  catch(error){(context==='preset'?presetMapStatus:signMapStatus)(error.message,true);}
}
