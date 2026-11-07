'use strict';
const bulkSign={mode:'normal',all:true,selected:new Set(),groups:[],loaded:false,busy:false,refreshing:false,
  group:'',code:'',point:'',device:false,run:null,timer:null,restored:false,generation:0,errors:[]};
function bulkUsers(){return state.accounts.filter(a=>a.status==='active'&&(bulkSign.all||bulkSign.selected.has(a.id)));}
function bulkGroup(){return bulkSign.groups.find(g=>g.key===bulkSign.group);}
function bulkKinds(){return bulkSign.mode==='gesture'?['gesture','code']:[bulkSign.mode];}
function bulkSignPanel(){
  const b=bulkSign,active=b.run&&!b.run.terminal,locked=b.busy||b.refreshing||active;
  const groups=b.groups.filter(g=>bulkKinds().includes(g.kind));
  const group=bulkGroup(),eligible=group?.targets.some(t=>bulkUsers().some(a=>a.id===t.id)&&!t.signed);
  const canRetry=b.run?.terminal&&group?.id===b.run.activity_id&&group.kind===b.run.kind&&group.phase===(b.run.phase||'in')&&b.run.accounts.some(a=>a.state==='failed');
  const points=(state.location_presets||[]).flatMap(s=>s.points.map(p=>({school:s.school,name:p.name})));
  return `<section class="panel" id="bulk-sign-panel"><div class="panel-header"><div><h3>所有用户签到</h3><p class="subheading">选择方式、用户和一个活动，再一键提交；已发出的任务由服务器继续处理。</p></div></div><div class="panel-body">
    <div class="actions">${[['qr','二维码扫描'],['location','定位签到'],['gesture','手势 / 签到码'],['normal','普通签到']].map(([mode,label])=>`<button type="button" class="button ${b.mode===mode?'primary':'secondary'}" data-bulk-mode="${mode}" ${locked?'disabled':''}>${label}</button>`).join('')}</div><div class="gap"></div>
    <label class="camera-switch"><input type="checkbox" id="bulk-all" ${b.all?'checked':''} ${locked?'disabled':''}>全选所有可用用户</label>
    <p class="setting-note">已选择 ${bulkUsers().length} 位用户；登录失效的用户请先到用户管理重新登录。</p>
    <div class="field-grid" ${b.all?'hidden':''}>${state.accounts.map(a=>`<label class="camera-choice"><input type="checkbox" name="bulk-user" value="${esc(a.id)}" ${b.selected.has(a.id)?'checked':''} ${locked||a.status!=='active'?'disabled':''}><span>${esc(a.name)}${a.status==='active'?'':'（登录失效）'}</span></label>`).join('')}</div>
    <div class="actions"><button type="button" class="button secondary" data-bulk="refresh" ${locked?'disabled':''}>${b.refreshing?'正在检查所选用户…':'刷新所选用户签到活动'}</button></div>
    ${b.errors.map(message=>`<p class="inline-error">${esc(message)}</p>`).join('')}
    <div class="field"><label for="bulk-activity">本次签到活动</label><select id="bulk-activity" ${locked?'disabled':''}><option value="">请选择一个进行中的活动</option>${groups.map(g=>`<option value="${esc(g.key)}" ${g.key===b.group?'selected':''}>${esc(g.title)} · ${esc(g.course)} · ${g.phase==='out'?'签退':'签到'} · 涉及 ${g.targets.length} 人</option>`).join('')}</select><small>${!b.loaded?'先刷新以获取所有所选用户的活动。':groups.length?'仅为有此活动的所选用户提交。':'所选用户暂无此方式的进行中活动。'}</small></div>
    <p class="setting-note">${bulkGroup()?`涉及用户：${bulkGroup().targets.map(t=>esc(t.name)+(t.signed?'（已完成）':'')).join('、')}`:''}</p>
    ${b.mode==='gesture'?`<div class="field"><label for="bulk-code">手势数字 / 签到码</label><input id="bulk-code" inputmode="numeric" maxlength="20" pattern="[0-9]{1,20}" value="${esc(b.code)}" ${locked?'disabled':''}><small>手势按九宫格数字顺序填写，签到码填写当前活动提供的数字。</small></div>`:''}
    ${b.mode==='location'?`<div id="bulk-device-option" ${window.DevicePosition?.available()?'':'hidden'}><label class="camera-switch"><input type="checkbox" id="bulk-device" ${b.device?'checked':''} ${locked?'disabled':''}>使用设备位置上报（本次所选用户共用）</label></div><div class="field" id="bulk-point-field" ${b.device&&window.DevicePosition?.available()?'hidden':''}><label for="bulk-point">本次实际所在位置</label><select id="bulk-point" ${locked?'disabled':''}><option value="">选择预设点位</option>${points.map(p=>{const value=JSON.stringify(p);return `<option value="${esc(value)}" ${b.point===value?'selected':''}>${esc(p.school+' · '+p.name)}</option>`;}).join('')}</select><small>点位和学校位置沿用现有配置。</small></div>`:''}
    <p id="bulk-message" class="setting-note"></p><div class="actions"><button type="button" class="button primary" data-bulk="start" ${locked||!eligible?'disabled':''}>${b.all?'一键为所有适用用户签到':'一键为所选用户签到'}</button><button type="button" class="button secondary" data-bulk="stop" ${!active?'disabled':''}>停止剩余任务</button><button type="button" class="button secondary" data-bulk="retry" ${!canRetry?'disabled':''}>仅重试失败用户</button></div>
    <p class="setting-note">滑块、人脸、拍照等需要逐人处理的要求会列出，不共用验证结果。二维码入口沿用连续扫码页面。</p><div id="bulk-results"></div></div></section>`;
}
function bulkDraw(){
  if(state.authenticated&&state.page==='sign'){
    const panel=document.getElementById('bulk-sign-panel');
    if(panel){panel.outerHTML=bulkSignPanel();bulkResults();}
  }
}
function bulkResults(){
  const target=document.getElementById('bulk-results'),run=bulkSign.run;if(!target||!run)return;
  const labels={pending:'等待提交',submitting:'正在提交',succeeded:'已完成',failed:'未成功',attention:'需要处理',skipped:'已跳过',cancelled:'已停止'};
  const done=run.accounts.filter(a=>!['pending','submitting'].includes(a.state)).length;
  target.innerHTML=`<p class="setting-note">批次活动 ${esc(run.activity_id)} · ${done}/${run.accounts.length} · ${run.terminal?'已结束':'服务器处理中'}</p><ol class="camera-queue">${run.accounts.map(a=>`<li><div class="camera-row-head"><strong>${esc(a.name)}</strong><span class="badge ${a.state==='succeeded'?'green':'purple'}">${esc(a.code==='location_rejected'?'上报失败':labels[a.state]||a.state)}</span></div><p>${esc(a.message)}</p>${['attention','failed'].includes(a.state)?`<button type="button" class="button secondary small" data-bulk="single" data-user="${esc(a.id)}" data-activity="${esc(run.activity_id)}">单独查看 / 处理</button>`:''}</li>`).join('')}</ol>`;
}
async function bulkMap(items,limit,fn){
  let next=0;await Promise.all(Array.from({length:Math.min(items.length,limit)},async()=>{while(next<items.length){const index=next++;await fn(items[index]);}}));
}
function bulkAggregate(rows){
  const groups=new Map();
  for(const {user,activities} of rows)for(const a of activities){
    if(a.source==='group'||a.photo||!['normal','location','gesture','code'].includes(a.kind))continue;
    const key=JSON.stringify([a.id,a.kind,a.phase||'in']);
    if(!groups.has(key))groups.set(key,{key,id:a.id,kind:a.kind,phase:a.phase||'in',title:a.title,course:a.course.title,targets:[]});
    const group=groups.get(key);if(!group.targets.some(t=>t.id===user.id))group.targets.push({id:user.id,name:user.name,signed:a.signed});
  }
  return [...groups.values()].sort((a,b)=>b.targets.length-a.targets.length);
}
async function bulkRefresh(){
  const b=bulkSign,users=bulkUsers();if(!users.length)throw new Error('请先选择用户');
  b.refreshing=true;b.errors=[];const generation=b.generation;bulkDraw();const rows=[];
  try{
    await bulkMap(users,5,async user=>{
      try{
        const data=await api(`/accounts/${encodeURIComponent(user.id)}/activities?source=course`);
        if(generation!==b.generation)return;
        state.activities[user.id]=data.activities;rows.push({user,activities:data.activities});
      }catch(error){if(generation===b.generation)b.errors.push(user.name+'：'+error.message);}
    });
    if(generation!==b.generation)return;
    b.groups=bulkAggregate(rows);b.loaded=true;
    const candidates=b.groups.filter(g=>bulkKinds().includes(g.kind));b.group=candidates.length===1?candidates[0].key:'';
  }finally{if(generation===b.generation){b.refreshing=false;bulkDraw();}}
}
async function bulkStart(retry=false){
  if(bulkSign.busy||bulkSign.run&&!bulkSign.run.terminal)return;
  const b=bulkSign,group=bulkGroup();if(!group)throw new Error('请先刷新并选择签到活动');
  if(retry&&(b.run.activity_id!==group.id||b.run.kind!==group.kind||(b.run.phase||'in')!==group.phase))throw new Error('请先选择原批次的同一个活动，再重试失败用户');
  const selected=new Set(bulkUsers().map(a=>a.id));
  const failed=new Set(retry?b.run.accounts.filter(a=>a.state==='failed').map(a=>a.id):[]);
  const ids=group.targets.filter(t=>selected.has(t.id)&&(retry?failed.has(t.id):!t.signed)).map(t=>t.id);
  if(!ids.length)throw new Error('本次没有需要提交的适用用户，请刷新活动核对');
  const data={account_ids:ids,activity_id:group.id,kind:group.kind,phase:group.phase};
  if(['gesture','code'].includes(group.kind))data.code=b.code.trim();
  const generation=b.generation;b.busy=true;bulkDraw();
  try{
    if(group.kind==='location'){
      if(b.device&&window.DevicePosition?.available()){
        document.getElementById('bulk-message').textContent='正在申请定位权限并获取设备当前位置…';
        data.device_location=await window.DevicePosition.get();
      }else{if(!b.point)throw new Error('请选择本次实际所在点位');data.location=JSON.parse(b.point);}
    }
    if(generation!==b.generation)return;
    const result=await api('/batch-sign','POST',data);
    if(generation!==b.generation)return;
    bulkAccept(result);
    bulkPoll();
  }finally{if(generation===b.generation){b.busy=false;bulkDraw();}}
}
function bulkPoll(){
  clearTimeout(bulkSign.timer);
  if(!bulkSign.run||bulkSign.run.terminal)return;
  const generation=bulkSign.generation,id=bulkSign.run.id;
  bulkSign.timer=setTimeout(async()=>{
    if(!state.authenticated||generation!==bulkSign.generation)return;
    try{
      const run=await api('/batch-sign/'+encodeURIComponent(id));if(generation!==bulkSign.generation)return;
      bulkAccept(run);if(run.terminal)bulkDraw();else bulkResults();
    }catch(error){if(error.status===401||error.status===403)return;}
    if(generation===bulkSign.generation)bulkPoll();
  },1000);
}
function bulkAccept(run){
  bulkSign.run=run;
  const completed=new Set(run.accounts.filter(a=>a.state==='succeeded').map(a=>a.id));
  for(const group of bulkSign.groups)if(group.id===run.activity_id&&group.kind===run.kind&&group.phase===(run.phase||'in'))
    for(const target of group.targets)if(completed.has(target.id))target.signed=true;
  for(const id of completed){const entry=state.activities?.[id]?.find(a=>a.id===run.activity_id);if(entry)entry.signed=true;}
}
async function restoreBulkSign(){
  if(bulkSign.restored)return;bulkSign.restored=true;const generation=bulkSign.generation;
  try{const data=await api('/batch-sign/current');if(generation!==bulkSign.generation)return;if(!bulkSign.run)bulkSign.run=data.run;bulkDraw();bulkPoll();}catch{bulkSign.restored=false;}
}
function resetBulkSign(){
  bulkSign.generation++;clearTimeout(bulkSign.timer);window.AndroidScanner?.cancelLocation?.();
  Object.assign(bulkSign,{groups:[],loaded:false,busy:false,refreshing:false,group:'',code:'',point:'',device:false,run:null,restored:false,errors:[],all:true,selected:new Set()});
}
document.addEventListener('click',async event=>{
  const mode=event.target.closest('[data-bulk-mode]');
  if(mode){if(mode.dataset.bulkMode==='qr'){navigate('sign-camera');return;}bulkSign.mode=mode.dataset.bulkMode;bulkSign.group='';bulkDraw();return;}
  const button=event.target.closest('[data-bulk]');if(!button||button.disabled)return;
  try{
    if(button.dataset.bulk==='refresh')await bulkRefresh();
    if(button.dataset.bulk==='start'||button.dataset.bulk==='retry')await bulkStart(button.dataset.bulk==='retry');
    if(button.dataset.bulk==='stop'&&bulkSign.run){bulkSign.run=await api('/batch-sign/'+encodeURIComponent(bulkSign.run.id)+'/stop','POST',{});bulkDraw();bulkPoll();}
    if(button.dataset.bulk==='single'){
      const user=button.dataset.user;state.activities[user]=(await api(`/accounts/${encodeURIComponent(user)}/activities?source=course`)).activities;
      state.active=user;syncAccountSwitch();openSign(button.dataset.activity);
    }
  }catch(error){toast(error.message,true);}
});
document.addEventListener('change',event=>{
  const el=event.target,b=bulkSign;
  if(el.id==='bulk-all'||el.name==='bulk-user'){
    if(el.id==='bulk-all'){if(!el.checked)b.selected=new Set(state.accounts.filter(a=>a.status==='active').map(a=>a.id));b.all=el.checked;}
    else if(el.checked)b.selected.add(el.value);else b.selected.delete(el.value);
    b.groups=[];b.loaded=false;b.group='';bulkDraw();
  }
  if(el.id==='bulk-activity'){b.group=el.value;bulkDraw();}
  if(el.id==='bulk-point')b.point=el.value;
  if(el.id==='bulk-device'){b.device=el.checked;bulkDraw();}
});
document.addEventListener('input',event=>{if(event.target.id==='bulk-code')bulkSign.code=event.target.value;});
