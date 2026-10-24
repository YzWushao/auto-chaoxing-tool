'use strict';

function presetOptions(schools) { return schools.map((s,i)=>`<option value="${i}">${esc(s.school)}</option>`).join(''); }
function schoolSuggestions() { return `<datalist id="school-suggestions">${(state.location_presets||[]).map(s=>`<option value="${esc(s.school)}"></option>`).join('')}</datalist>`; }
function schoolSelectOptions(selected='') { return '<option value="">选择已建学校</option>'+(state.location_presets||[]).map(s=>`<option value="${esc(s.school)}" ${s.school===selected?'selected':''}>${esc(s.school)}</option>`).join(''); }
function presetsMapHTML() {
  return `<section id="school-presets" class="school-presets" aria-label="学校教学楼预设"><div class="location-toolbar"><strong>学校 → 点位</strong>${button('导入 JSON','presets-import','secondary small')}<a class="text-button" href="/api/location-presets/export" download>导出 JSON</a><a class="text-button" href="#presets" data-action="presets-manage">管理点位 ↗</a><input id="school-presets-file" class="hidden" type="file" accept=".json,application/json"></div><div class="preset-selectors"><div class="field"><label for="preset-school">学校名称</label><select id="preset-school"><option value="">选择学校</option>${presetOptions(state.location_presets||[])}</select></div><div class="field"><label for="preset-point">教学楼 / 教学区</label><select id="preset-point" disabled><option value="">先选择学校</option></select></div>${button('应用点位','presets-apply','secondary small')}</div><details class="preset-save"><summary>新建学校</summary><div class="map-search-row"><input id="inline-school-name" maxlength="100" aria-label="新学校名称" placeholder="输入学校全称">${button('创建学校','school-inline-create','secondary small')}</div></details><details class="preset-save"><summary>将当前坐标保存为点位</summary><div class="preset-selectors"><div class="field"><label for="save-point-school">所属学校（父级）</label><select id="save-point-school">${schoolSelectOptions()}</select></div><div class="field"><label for="save-point-name">教学楼 / 教学区名称</label><input id="save-point-name" maxlength="100" placeholder="例如：A 教学楼"></div>${button('保存当前点位','presets-save-current','primary small')}</div></details><p id="presets-message" class="setting-note" role="status">先新建学校，再添加子点位。数量不限，SQLite 持久保存；保存或应用点位不会提交签到。</p></section>`;
}

function presetsPage() {
  const schools=state.location_presets||[], total=schools.reduce((n,s)=>n+s.points.length,0);
  return heading('预设点位','设置 / 预设点位 · 学校是父级，教学楼 / 教学区是子点位。',`<a class="button secondary" href="#settings">返回设置</a>`+button('新建学校','school-new','primary'))+
    `<section class="panel"><div class="panel-header"><h3>${schools.length} 所学校 · ${total} 个点位</h3><div class="actions">${button('导入 JSON','presets-import','secondary small')}<a class="button secondary small" href="/api/location-presets/export" download>导出全部 JSON</a><a class="text-button" href="/static/examples/location-presets.example.json" download="学校点位示例.json">示例 JSON</a></div></div><div class="panel-body"><input id="school-presets-file" class="hidden" type="file" accept=".json,application/json"><p class="setting-note" id="presets-message" role="status">先新建学校，再在该学校下通过地图新增点位。学校和点位数量不限；JSON 仅含学校与点位，不含账号、Cookies 或 API 密钥。</p></div></section>`+
    (!schools.length?`<section class="panel">${empty('先创建一所学校','学校可以暂时没有点位，之后可逐个通过地图添加。',button('新建学校','school-new','primary'),'sign')}</section>`:schools.map((s,si)=>`<section class="panel school-group"><div class="panel-header"><div><h3>${esc(s.school)}</h3><p class="subheading">父级学校 · ${s.points.length} 个子点位</p></div><div class="actions">${button('新增点位','preset-new','primary small','',`data-school="${si}"`)}${button('重命名学校','school-edit','secondary small','',`data-school="${si}"`)}${button('删除学校','school-delete','secondary small','',`data-school="${si}"`)}</div></div><div class="panel-body">${!s.points.length?'<p class="setting-note">此学校还没有子点位，点击“新增点位”在地图上选取。</p>':`<div class="presets-table-wrap"><table class="presets-table"><thead><tr><th>教学楼 / 教学区</th><th>坐标系</th><th>经度 / 纬度</th><th>位置说明</th><th>操作</th></tr></thead><tbody>${s.points.map((p,pi)=>`<tr><td><strong>${esc(p.name)}</strong></td><td>${esc(p.coordinate_system||s.coordinate_system).toUpperCase()}</td><td><code>${Number(p.longitude).toFixed(6)}<br>${Number(p.latitude).toFixed(6)}</code></td><td>${esc(p.address)}</td><td><div class="actions">${button('编辑','preset-edit','secondary small','',`data-school="${si}" data-point="${pi}"`)}${button('删除','preset-delete','secondary small','',`data-school="${si}" data-point="${pi}"`)}</div></td></tr>`).join('')}</tbody></table></div>`}</div></section>`).join(''));
}
function presetsSettingsEntry() {
  return `<section class="panel"><div class="panel-header"><div><h3>预设点位</h3><p class="subheading">按学校保存教学楼与教学区，支持新增、编辑、删除、JSON 导入 / 导出</p></div><a class="button secondary" href="#presets">管理预设点位 →</a></div></section>`;
}
function openSchoolEditor(index) {
  const school=(state.location_presets||[])[index]; state.editSchoolOriginal=school?.school||null;
  $('#modal-content').innerHTML=`<form id="school-edit-form"><div class="modal-head"><h2>${school?'重命名学校':'新建学校'}</h2><button type="button" class="icon-button" data-action="modal-close" aria-label="关闭">×</button></div><div class="modal-body"><div class="field"><label for="school-edit-name">学校名称</label><input id="school-edit-name" name="name" maxlength="100" required value="${esc(school?.school||'')}" placeholder="输入学校全称"></div><p class="setting-note">学校作为父级，可以先创建空学校，再在它下面通过地图新增教学楼 / 教学区点位。</p><p id="school-edit-error" class="inline-error" role="alert"></p></div><div class="modal-actions"><button class="button secondary" type="button" data-action="modal-close">取消</button><button class="button primary" type="submit">${school?'保存学校名称':'创建学校'}</button></div></form>`;
  $('#modal').showModal();
}
async function saveSchoolEditor(form) {
  const data=await api('/location-presets/school','PUT',{name:form.elements.name.value.trim(),original:state.editSchoolOriginal});
  presetsUpdated(data.location_presets); $('#modal').close(); toast('学校已保存，可在学校下面新增点位');
}
function openPresetEditor(si,pi) {
  closePresetMap(); state.presetMapPoint=null; state.presetMapAddress='';
  const school=(state.location_presets||[])[si], point=school?.points[pi];
  if(/^地图选点（[-\d.,\s]+）$/.test(point?.address||'')) state.presetMapAddress=point.address;
  state.editPresetOriginal=point?{school:school.school,name:point.name}:null;
  $('#modal-content').innerHTML=`<form id="preset-edit-form"><div class="modal-head"><h2>${point?'编辑':'新增'}预设点位</h2><button type="button" class="icon-button" data-action="modal-close" aria-label="关闭">×</button></div><div class="modal-body"><div class="field"><label for="edit-point-school">学校名称</label><input id="edit-point-school" name="school" value="${esc(school?.school||'')}" list="school-suggestions" maxlength="100" required></div>${schoolSuggestions()}<div class="field"><label for="edit-point-name">教学楼 / 教学区名称</label><input id="edit-point-name" name="name" value="${esc(point?.name||'')}" maxlength="100" required></div><div class="field"><label for="edit-point-system">坐标系</label><select id="edit-point-system" name="coordinate_system">${[['bd09','百度 BD-09'],['gcj02','高德 / 腾讯 GCJ-02'],['wgs84','GPS / OpenStreetMap WGS84']].map(([s,label])=>`<option value="${s}" ${s===(point?.coordinate_system||school?.coordinate_system||'bd09')?'selected':''}>${label}</option>`).join('')}</select></div><div class="field-grid"><div class="field"><label for="edit-point-lng">经度</label><input id="edit-point-lng" name="longitude" type="number" step="any" min="-180" max="180" required value="${esc(point?.longitude??'')}"></div><div class="field"><label for="edit-point-lat">纬度</label><input id="edit-point-lat" name="latitude" type="number" step="any" min="-90" max="90" required value="${esc(point?.latitude??'')}"></div></div><div class="field"><label for="edit-point-address">位置说明</label><input id="edit-point-address" name="address" maxlength="200" value="${esc(point?.address||'')}" placeholder="留空则使用学校和点位名称"></div><p class="setting-note">更改坐标系只修改该点位标记，不自动转换输入数值。请确保经纬度与所选坐标系一致。</p><p id="preset-edit-error" class="inline-error" role="alert"></p></div><div class="modal-actions"><button class="button secondary" type="button" data-action="modal-close">取消</button><button class="button primary" type="submit">保存点位</button></div></form>`;
  $('#modal').showModal();
  $('#modal').classList.add('preset-map-expanded');
  const body=$('#preset-edit-form .modal-body'), fields=document.createElement('div');
  fields.className='preset-editor-fields';
  while(body.firstChild) fields.append(body.firstChild);
  body.classList.add('preset-editor-grid'); body.append(fields);
  const schoolSelect=document.createElement('select'); schoolSelect.id='edit-point-school'; schoolSelect.name='school'; schoolSelect.required=true;
  schoolSelect.innerHTML=schoolSelectOptions(school?.school||''); $('#edit-point-school').replaceWith(schoolSelect);
  $('#school-suggestions',fields)?.remove();
  const panel=document.createElement('section'); panel.className='preset-editor-map';
  panel.setAttribute('aria-label','可视化选点');
  panel.innerHTML=mapSearchHTML('preset')+`<div class="sign-map-controls">${button('使用地图中心','preset-map-center','secondary small')}${button('按已填坐标定位','preset-map-input','secondary small')}</div><div id="preset-map-canvas" class="sign-map-canvas" role="region" aria-label="预设点位选点地图"></div><p id="preset-map-status" class="sign-map-message" role="status">搜索学校 / 地点后，拖动地图或标记精调；地图停止拖动时读取中心坐标。</p><p class="setting-note">底图 © OpenStreetMap contributors。6 位小数是保存精度，实际误差取决于定位、底图和坐标转换。这里仅保存点位，不发起签到。</p>`;
  body.prepend(panel);
  $('.setting-note',fields).textContent='搜索只作粗定位；可拖动地图或标记精调。已选地图点会随坐标系切换转换，手填数值不静默转换。';
  try {
    state.presetMap=SignMap.mount($('#preset-map-canvas'),{L:window.L,onSelect:fillPresetMap,onStatus:presetMapStatus});
    if(point) centerPresetMap();
  } catch(error) { presetMapStatus(error.message,true); }
}

function presetMapStatus(message,error=false) {
  const el=$('#preset-map-status'); if(el) {el.textContent=message;el.classList.toggle('error',error);}
}
function fillPresetMap(point) {
  state.presetMapPoint=point;
  const value=SignMap.formatted(point,$('#edit-point-system').value);
  $('#edit-point-lng').value=value.longitude; $('#edit-point-lat').value=value.latitude;
  const address=$('#edit-point-address');
  if(!address.value || address.value===state.presetMapAddress) { state.presetMapAddress=`地图选点（${value.longitude}, ${value.latitude}）`; address.value=state.presetMapAddress; }
  presetMapStatus(`已选：经度 ${value.longitude}，纬度 ${value.latitude}。填写学校与点位名称后保存。`);
}
function centerPresetMap() {
  try { state.presetMap?.center(SignMap.toWGS84(SignMap.point($('#edit-point-lng').value,$('#edit-point-lat').value),$('#edit-point-system').value)); }
  catch(error) { presetMapStatus(error.message,true); }
}
function closePresetMap() {
  stopMapSearch('preset'); state.presetMap?.destroy(); state.presetMap=null; state.presetMapPoint=null;
  $('#modal').classList.remove('preset-map-expanded');
}

function mapSearchHTML(context) {
  return `<div class="map-place-search"><label for="${context}-map-query">搜索学校 / 地点</label><div class="map-search-row"><input id="${context}-map-query" maxlength="120" placeholder="输入学校名或公开地名，按 Enter 搜索" autocomplete="off">${button('搜索','map-search','secondary small','',`data-context="${context}"`)}</div><div id="${context}-map-results" class="map-search-results"></div><p id="${context}-map-search-status" class="setting-note" role="status">仅点击搜索时将关键词发送给 Nominatim；不发送超星凭据。只搜公开地名，勿输入私人地址。<a href="https://operations.osmfoundation.org/policies/nominatim/" target="_blank" rel="noopener noreferrer">使用政策</a>：限流、缓存，无自动补全；无结果时可拖动地图。</p></div>`;
}
function stopMapSearch(context) {
  state[context+'MapSearchAbort']?.abort(); state[context+'MapSearchAbort']=null; state[context+'MapResults']=[];
}
async function runMapSearch(context) {
  stopMapSearch(context);
  const input=$(`#${context}-map-query`), result=$(`#${context}-map-results`), status=$(`#${context}-map-search-status`), map=state[context+'Map'];
  if(!input || !map) return;
  const controller=new AbortController(); state[context+'MapSearchAbort']=controller;
  const valid=()=>!controller.signal.aborted && $('#modal').open && state[context+'Map']===map && input.isConnected;
  result.replaceChildren();
  try {
    status.textContent='正在搜索公开地名…';
    const data=await api('/map/search','POST',{query:input.value.trim()},{signal:controller.signal});
    if(!valid()) return;
    state[context+'MapResults']=data.results;
    result.innerHTML=data.results.map((p,i)=>`<button type="button" data-action="map-search-result" data-context="${context}" data-index="${i}">${esc(p.name)}</button>`).join('');
    status.textContent=data.results.length?'© OpenStreetMap contributors · 选择结果跳到大致位置，再拖动地图精调。':'没有匹配结果；可增加城市名称、缩短学校名，或直接拖动地图。';
  } catch(error) { if(valid() && error.name!=='AbortError') status.textContent=error.message; }
}
function chooseMapSearch(context,index) {
  const value=state[context+'MapResults']?.[index]; if(!value) return;
  state[context+'Map']?.center(SignMap.point(value.longitude,value.latitude),15);
  $(`#${context}-map-results`).replaceChildren();
  $(`#${context}-map-search-status`).textContent='已跳转至搜索结果附近（© OpenStreetMap contributors）。拖动地图或标记精调后再保存。';
}
function presetsUpdated(values,school) {
  state.location_presets=values;
  if(state.page==='presets') render();
  if($('#school-presets')) {
    $('#school-presets').outerHTML=locationPresetsHTML();
    if(school) { $('#preset-school').value=String(values.findIndex(s=>s.school===school)); presetSchoolChanged(); }
  }
}
async function saveCurrentPoint() {
  const point={name:$('#save-point-name').value.trim(),longitude:$('#sign-longitude').value,latitude:$('#sign-latitude').value,address:$('#sign-address').value.trim(),coordinate_system:$('#sign-coordinate-system').value};
  const school=$('#save-point-school').value.trim();
  SignMap.point(point.longitude,point.latitude);
  if(!point.address) delete point.address;
  const data=await api('/location-presets/point','PUT',{school,point});
  presetsUpdated(data.location_presets,school); toast('当前点位已保存，未提交签到');
}
async function savePresetEditor(form) {
  const payload=Object.fromEntries(new FormData(form)), school=payload.school; delete payload.school;
  if(!payload.address.trim()) delete payload.address;
  const data=await api('/location-presets/point','PUT',{school,point:payload,original:state.editPresetOriginal});
  presetsUpdated(data.location_presets); $('#modal').close(); toast('预设点位已保存');
}
