'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const activeStates = new Set(['queued','running','waiting','stopping']);
const titles = {overview:'总览',study:'刷课中心','study-config':'刷课参数',sign:'签到中心',accounts:'用户管理',settings:'设置'};
const jobLabels = {queued:'排队中',running:'运行中',waiting:'等待输入',stopping:'正在停止',succeeded:'已完成',partial:'部分完成',failed:'失败',cancelled:'已停止',interrupted:'已中断'};
const kindLabels = {normal:'普通签到',gesture:'手势签到',qr:'二维码签到',location:'位置签到',photo:'拍照签到',code:'签到码'};
const labels = {provider:'题库 / API 提供方',endpoint:'API Endpoint',key:'API Key',model:'模型名称',tokens:'题库 Token',submit:'自动提交章节检测',cover_rate:'最低题库覆盖率',delay:'题目查询间隔（秒）',check_llm_connection:'启动时检查 AI 连接',min_interval_seconds:'AI 请求间隔（秒）',http_proxy:'代理地址',likeapi_search:'LIKE 联网搜索',likeapi_vision:'LIKE 视觉能力',likeapi_model:'LIKE 模型',likeapi_retry:'LIKE 自动重试',likeapi_retry_times:'LIKE 重试次数',url:'TikuAdapter 服务地址',go_authorization:'GO 题库授权 Token',go_min_interval:'GO 请求间隔（秒）',go_retry_times:'GO 重试次数',go_retry_backoff:'GO 退避基数',siliconflow_key:'硅基流动 API Key',siliconflow_model:'硅基流动模型',siliconflow_endpoint:'硅基流动 Endpoint',manual_mode_default:'手动答题模式',manual_mode_separator:'手动答题分隔符',true_list:'判断题正确词表',false_list:'判断题错误词表'};
const secrets = new Set(['key','tokens','siliconflow_key','go_authorization']);
const state = {csrf:'',authenticated:false,accounts:[],jobs:[],events:[],settings:{api:{}},schema:{api:{},providers:[]},active:'',page:'overview',courses:{},activities:{},selection:{},logJob:null,logAfter:0,logLoading:false,qrTimer:null,qrId:null,pollBusy:false};
const current = () => state.accounts.find(a => a.id === state.active);
const date = stamp => stamp ? new Date(stamp).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';

async function api(path, method='GET', data) {
  const response = await fetch('/api' + path, {method,credentials:'same-origin',headers: {'Content-Type':'application/json','X-CSRF-Token':state.csrf},...(data !== undefined ? {body:JSON.stringify(data)} : {})});
  let payload;
  try { payload = await response.json(); } catch { throw new Error('服务器返回了异常响应，请检查服务是否运行'); }
  if (!response.ok) {
    if (response.status === 401) { state.authenticated = false; showLogin(); }
    throw new Error(payload.error || `请求失败 (${response.status})`);
  }
  return payload;
}

function toast(message, error=false) {
  const el = document.createElement('div'); el.className = 'toast' + (error ? ' error' : ''); el.textContent = message;
  $('#toasts').append(el); setTimeout(() => el.remove(), 6000);
}

async function busy(button, fn, label='处理中…') {
  if (!button || button.disabled) return;
  const old = button.innerHTML; button.disabled = true; button.textContent = label;
  try { await fn(); } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.innerHTML = old; }
}

function empty(title, description, button='', symbol='study') {
  return `<div class="empty"><div class="empty-icon">${icon(symbol)}</div><h3>${esc(title)}</h3><p>${esc(description)}</p>${button}</div>`;
}
function heading(title, subtitle, actions='') { return `<div class="page-heading"><div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="actions">${actions}</div></div>`; }
function button(label, action, cls='secondary', symbol='', extra='') { return `<button type="button" class="button ${cls}" data-action="${action}" ${extra}>${symbol?icon(symbol):''}${esc(label)}</button>`; }

function showLogin() {
  $('#loading').classList.add('hidden'); $('#app-screen').classList.add('hidden'); $('#login-screen').classList.remove('hidden');
  $('#cancel-login').classList.toggle('hidden', !state.authenticated);
  $('#login-title').textContent = state.authenticated ? '添加或重新登录用户' : '登录你的超星账号';
  $('#login-error').textContent = '';
}

function stopQR() { clearTimeout(state.qrTimer); state.qrTimer=null; state.qrId=null; }

async function startQR() {
  stopQR(); $('#qr-image').textContent = '正在获取二维码…'; $('#qr-status').textContent = '请使用学习通 App 扫码并确认登录';
  try {
    const qr = await api('/auth/qr','POST',{}); state.qrId = qr.id;
    const image = document.createElement('img'); image.src = qr.image; image.alt = '超星登录二维码';
    $('#qr-image').replaceChildren(image);
    const poll = async () => {
      if (state.qrId !== qr.id) return;
      try {
        const result = await api(`/auth/qr/${encodeURIComponent(qr.id)}/poll`, 'POST', {});
        if (state.qrId !== qr.id) return;
        if (result.state === 'confirmed') { await afterLogin(result); return; }
        const text = {waiting:'请使用学习通 App 扫码并确认登录',scanned:'已扫码，请在学习通 App 中确认',expired:'二维码已过期，请点击刷新',cancelled:'登录已取消，可以刷新二维码重试'};
        $('#qr-status').textContent = text[result.state] || '等待平台确认…';
        if (!['expired','cancelled'].includes(result.state)) state.qrTimer = setTimeout(poll,2500);
      } catch (error) { $('#login-error').textContent=error.message; }
    };
    state.qrTimer = setTimeout(poll,2500);
  } catch(error) { $('#qr-image').textContent='二维码暂不可用'; $('#login-error').textContent=error.message; }
}

async function afterLogin(result) {
  stopQR(); state.csrf = result.csrf; state.authenticated = true; state.active = result.account.id;
  $('#password').value = ''; await bootstrap(); location.hash = '#overview'; render();
}

async function bootstrap() {
  const data = await api('/bootstrap'); Object.assign(state,data);
  if (!state.accounts.some(a => a.id === state.active)) state.active = state.accounts[0]?.id || '';
  for(const a of state.accounts) if(!state.selection[a.id]) state.selection[a.id] = new Set(a.config.course_keys);
  $('#login-screen').classList.add('hidden'); $('#loading').classList.add('hidden'); $('#app-screen').classList.remove('hidden');
  syncAccountSwitch(); render();
}

function syncAccountSwitch() {
  $('#account-switch').innerHTML = state.accounts.map(a => `<option value="${esc(a.id)}" ${a.id===state.active?'selected':''}>${esc(a.name)}${a.status==='expired'?' · 已失效':''}</option>`).join('') || '<option>尚无用户</option>';
  $('#avatar').textContent = current()?.name?.slice(0,1) || 'A';
}

function navigate(page) { location.hash = '#' + page; if (state.page===page) render(); }

function render() {
  if (!state.authenticated) return;
  const page = location.hash.slice(1); state.page = titles[page] ? page : 'overview';
  $('#breadcrumb-title').textContent=titles[state.page];
  $$('#nav a').forEach(a => a.classList.toggle('active', a.dataset.page === (state.page==='study-config'?'study':state.page)));
  const renderers = {overview:overviewPage,study:studyPage,'study-config':configPage,sign:signPage,accounts:accountsPage,settings:settingsPage};
  $('#page-content').innerHTML = renderers[state.page]();
  if (state.page==='study' && state.logJob) { state.logAfter=0; loadLogs(); }
}

function overviewPage() {
  const name=current()?.name || '新用户';
  const metrics=[['已连接用户',state.accounts.length,'独立会话，独立配置','user'],['运行中任务',state.jobs.filter(j=>activeStates.has(j.state)).length,'任务在后台持续运行','play'],['已完成任务',state.jobs.filter(j=>j.state==='succeeded').length,'最近 50 条任务记录','check'],['签到成功',state.events.filter(e=>e.kind==='sign_success').length,'最近活动记录中的成功次数','sign']];
  return heading('你好，'+name+' 👋','在这里安排课程任务，查看签到与运行状态。',`<span class="date-chip">${new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'long'})}</span>`)+
    `<section class="hero"><div><div class="eyebrow">YOUR LEARNING, IN ONE PLACE</div><h2>今天的学习计划，<br>从这里开始。</h2><p>选择目标课程，设置学习参数，让每个账号按自己的计划运行。</p>${button('进入刷课中心','go-study','primary','arrow')}</div><div class="hero-decoration">${icon('study')}</div></section>`+
    `<section class="metrics">${metrics.map(([label,count,foot,sym])=>`<div class="metric"><div><small>${label}</small><strong>${count}</strong><div class="foot">${foot}</div></div><div class="metric-icon">${icon(sym)}</div></div>`).join('')}</section>`+
    `<div class="columns"><section class="panel"><div class="panel-header"><h3>最近任务</h3><a class="text-button" href="#study">查看全部 →</a></div><div id="overview-jobs">${jobsHTML(state.jobs.slice(0,3))}</div></section><section class="panel"><div class="panel-header"><h3>快捷入口</h3><small>常用功能</small></div><div class="panel-body"><a class="quick-link" href="#sign">${icon('sign')}<div><h3>查看签到活动</h3><p>获取当前用户的课程签到</p></div><span>↗</span></a><a class="quick-link" href="#accounts">${icon('user')}<div><h3>管理多个用户</h3><p>查看会话与独立配置</p></div><span>↗</span></a><a class="quick-link" href="#settings">${icon('settings')}<div><h3>全局 API 设置</h3><p>统一配置，按需覆盖</p></div><span>↗</span></a></div></section></div>`+
    `<section class="panel"><div class="panel-header"><h3>最近动态</h3><small>登录 · 刷课 · 签到</small></div><div class="panel-body" id="overview-events">${eventsHTML()}</div></section>`;
}

function eventsHTML() {
  return state.events.slice(0,6).map(e=>`<div class="event"><span class="dot"></span><div><p>${esc(e.message)}</p><time>${date(e.created_at)}</time></div></div>`).join('') || '<p class="setting-note">暂时没有动态，后续任务结果会显示在这里。</p>';
}

function elapsed(value) {
  const seconds=Math.max(0,Math.floor(Number(value)||0));
  return [Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].map(n=>String(n).padStart(2,'0')).join(':');
}

function watchHTML(watch, jobState) {
  if(!watch) return '';
  const items=watch.active?.length?watch.active:watch.last?[watch.last]:[];
  return `<div class="watch-summary"><b>媒体计时累计 ${elapsed(watch.elapsed_seconds)}</b><span>已计时完成 ${watch.completed||0} / ${watch.total||0} 个媒体</span></div>${items.map(m=>`<div class="media-progress"><div class="media-heading"><strong>${esc(m.title)}</strong><span class="badge ${m.state==='completed'?'green':m.state==='error'?'red':'purple'}">${m.acknowledged?'任务点已确认':!activeStates.has(jobState)?'已结束':m.state==='error'?'上报失败':'计时中'}</span></div><small>${esc(m.course)}</small><progress max="${Math.max(Number(m.duration)||1,1)}" value="${Math.max(Number(m.position)||0,0)}" aria-label="${esc(m.title)} 播放进度"></progress><div class="media-time"><span>${elapsed(m.position)} / ${elapsed(m.duration)}</span><span>实际运行 ${elapsed(m.elapsed_seconds)} · ${esc(m.speed)}×</span></div></div>`).join('')}<p class="media-note">计时为后台运行时间（并行累加）；平台观看时长以官方统计为准。</p>`;
}

function jobsHTML(jobs) {
  if (!jobs.length) return empty('暂时没有任务','选好课程和配置后，点击“开始任务”即可创建。','','log');
  return jobs.map(j=>{
    const p=j.progress, total=p.total||0, finished=(p.done||0)+(p.failed||0)+(p.skipped||0);
    const color=j.state==='succeeded'?'green':['failed','interrupted'].includes(j.state)?'red':['partial','waiting'].includes(j.state)?'orange':'purple';
    const name=state.accounts.find(a=>a.id===j.account_id)?.name || '已移除用户';
    return `<article class="job"><div class="job-head"><h3>${esc(name)} 的学习任务</h3><span class="badge ${color}">${jobLabels[j.state]||esc(j.state)}</span></div><div class="job-info"><span>${total?`章节 ${finished} / ${total} · 完成 ${p.done||0}`:'正在准备 / 等待任务进度'}</span><span>${date(j.created_at)}</span></div><progress max="${Math.max(total,1)}" value="${finished}"></progress>${watchHTML(p.watch,j.state)}<div class="job-actions"><button class="text-button" data-action="job-log" data-id="${j.id}">查看日志 →</button>${activeStates.has(j.state)?`<button class="text-button" data-action="job-stop" data-id="${j.id}">停止任务</button>`:''}${p.failed?`<span class="badge red">${p.failed} 个失败</span>`:''}${p.skipped?`<span class="badge orange">${p.skipped} 个跳过</span>`:''}</div></article>`;
  }).join('');
}

function studyPage() {
  const a=current(); if(!a) return heading('刷课中心','连接一个用户后开始。')+empty('请先添加用户','使用手机号或二维码连接超星账号。',button('添加用户','add-account','primary'),'user');
  return heading('刷课中心','为 '+a.name+' 选择课程，查看任务进度和日志。',button('刷课参数','go-study-config','secondary','settings')+button('开始任务','study-start','primary','play'))+
    (a.status==='expired'?'<div class="notice">此用户登录已失效，请点击右上角“＋”重新登录同一账号。</div>':'')+
    `<div class="columns"><div><section class="panel"><div class="panel-header"><div><h3>目标课程</h3><p class="subheading">课程与班级分别选择，目标仅对当前用户生效</p></div>${button('刷新课程','courses-refresh','secondary small','refresh')}</div><div class="toolbar"><input id="course-search" placeholder="搜索课程或教师" aria-label="搜索课程或教师"><span class="selection-info">已选择 <b id="selection-count">${state.selection[a.id]?.size||0}</b> 门</span></div><div id="course-list">${coursesHTML()}</div><div class="panel-actions"><small>仅运行已保存的目标课程</small>${button('全选 / 清空','courses-toggle','secondary small')}${button('保存目标','courses-save','primary small')}</div></section><section class="panel"><div class="panel-header"><h3>运行日志</h3><small id="log-caption">${state.logJob?'任务 '+esc(state.logJob.slice(0,8)):'选择一条任务查看'}</small></div><div class="log-box" id="job-logs">${state.logJob?'正在读取任务日志…':'任务日志会显示在这里。'}</div><div id="job-prompt"></div></section></div><aside><section class="panel"><div class="panel-header"><h3>当前用户配置</h3><a href="#study-config" class="text-button">编辑 →</a></div><div class="panel-body"><div class="setting-row"><span>学习模式</span><b>${a.config.study.study_mode==='task'?'仅完成任务点':'按时长学习'}</b></div><div class="setting-row"><span>视频倍速</span><b>${esc(a.config.study.speed)} ×</b></div><div class="setting-row"><span>并行课程</span><b>${a.config.study.jobs} 门</b></div><div class="setting-row"><span>API 来源</span><b>${a.config.inherit_api?'全局配置':'用户独立配置'}</b></div><div class="setting-row"><span>题库 / 模型</span><b>${esc((a.config.inherit_api?state.settings.api:a.config.api).provider||'未启用')}</b></div></div></section><section class="panel"><div class="panel-header"><h3>任务队列</h3><small>当前用户</small></div><div id="study-jobs">${jobsHTML(state.jobs.filter(j=>j.account_id===a.id))}</div></section></aside></div>`;
}

function coursesHTML(filter='') {
  const a=current(), list=state.courses[a?.id];
  if(!list) return empty('加载你的课程','点击“刷新课程”，通过统一登录会话读取课程。');
  const filtered=list.filter(c=>(c.title+' '+c.teacher).toLowerCase().includes(filter.toLowerCase()));
  if(!filtered.length) return empty(list.length?'没有匹配的课程':'暂无可用课程','可以刷新课程列表或检查所选账号。');
  return filtered.map(c=>`<label class="course-row"><input type="checkbox" data-course="${esc(c.key)}" ${state.selection[a.id]?.has(c.key)?'checked':''} aria-label="选择 ${esc(c.title)}"><span class="course-icon">${icon('study')}</span><span><span class="course-name">${esc(c.title)}</span><span class="course-meta">${esc(c.teacher||'未标注教师')} · 课程 ${esc(c.courseId)} · 班级 ${esc(c.clazzId)}</span></span><span class="badge">可选课程</span></label>`).join('');
}

function apiFields(config) {
  const basics=['provider','endpoint','key','model','tokens','submit','cover_rate','min_interval_seconds'];
  const field=key=>{
    const value=config[key] ?? state.schema.api[key] ?? '';
    let input;
    if(['true','false'].includes(state.schema.api[key])) input=`<select name="api.${key}" id="api-${key}"><option value="false" ${value==='false'?'selected':''}>关闭</option><option value="true" ${value==='true'?'selected':''}>开启</option></select>`;
    else input=`<input id="api-${key}" name="api.${key}" type="${secrets.has(key)?'password':'text'}" value="${esc(value)}" ${key==='provider'?'list="provider-options"':''} placeholder="${key==='provider'?'留空表示不启用题库':secrets.has(key)?'未设置；填写后保存':key==='endpoint'?'https://example.com/v1':'按需填写'}" autocomplete="off">`;
    return `<div class="field"><label for="api-${key}">${esc(labels[key]||key)}</label>${input}${key==='provider'?'<small>支持英文逗号分隔多个提供方，按顺序回退。</small>':key==='key'||key==='tokens'?'<small>已保存的密钥显示为圆点；清空后保存可移除。</small>':''}</div>`;
  };
  return `<datalist id="provider-options">${state.schema.providers.map(p=>`<option value="${p}">`).join('')}</datalist><div class="field-grid">${basics.map(field).join('')}</div><details><summary>高级题库参数 · 硅基流动 / LIKE / GO / 手动模式</summary><div class="field-grid">${Object.keys(state.schema.api).filter(k=>!basics.includes(k)).map(field).join('')}</div></details>`;
}

function timingFields(s) {
  const duration=(s.study_mode||'duration')==='duration';
  return `<div class="field-grid"><div class="field"><label for="study-mode">学习模式</label><select id="study-mode" name="study.study_mode"><option value="duration" ${duration?'selected':''}>按时长学习（推荐）</option><option value="task" ${!duration?'selected':''}>仅完成任务点（上游原逻辑）</option></select></div><div class="field check-field"><input id="study-replay" type="checkbox" name="study.replay_completed" ${s.replay_completed!==false?'checked':''}><label for="study-replay">从头计时，包含已完成的视频</label></div></div><div class="notice purple" id="timing-notice">${timingNotice(duration)}</div><div class="gap"></div>`;
}

function timingNotice(duration) {
  return duration?'按真实经过时间推进并周期上报，任务点提前通过也不会停止计时。1 倍速时，媒体时长约等于运行时长。已完成章节仅重看媒体，不重交已完成的测验。':'保留上游的完成即跳过和快速完成逻辑，可能很快结束。需要增加观看时长时请选择“按时长学习”。';
}

function creditsPanel() {
  return `<section class="panel credits"><div class="panel-header"><h3>开源来源与致谢</h3><a class="text-button" href="/legal/sources" target="_blank" rel="noopener noreferrer">完整引用与修改记录 ↗</a></div><div class="panel-body"><p>本项目直接复用刷课引擎，并参考签到项目的接口流程进行 Python 适配。感谢两个项目的作者与贡献者。</p><div class="credit-grid"><article><h3><a href="https://github.com/Samueli924/chaoxing" target="_blank" rel="noopener noreferrer">Samueli924/chaoxing ↗</a></h3><p>刷课引擎及资源 · GPL-3.0</p><small>参考版本 45d2106 · 修改日期 2026-10-23</small></article><article><h3><a href="https://github.com/Yink-Design/chaoxing-sign-cli" target="_blank" rel="noopener noreferrer">Yink-Design/chaoxing-sign-cli ↗</a></h3><p>签到接口流程参考 · MIT</p><small>Copyright (c) 2021 miaochenxi · 参考版本 4084545</small></article></div><p class="setting-note">本整合项目按 GPLv3 授权，按原样提供，不附带担保。原项目的版权和许可声明予以保留。</p><div class="actions"><a class="text-button" href="/legal/license" target="_blank" rel="noopener noreferrer">GPLv3 许可证</a><a class="text-button" href="/legal/sign-mit" target="_blank" rel="noopener noreferrer">签到上游 MIT 许可证</a><a class="text-button" href="/legal/notice" target="_blank" rel="noopener noreferrer">版权与引用声明</a></div></div></section>`;
}

function configPage() {
  const a=current(); if(!a) return accountsPage(); const s=a.config.study;
  return heading('刷课参数','独立配置 '+a.name+' 的学习方式和 API。',button('返回刷课中心','go-study','secondary','arrow'))+
    `<form id="study-config-form"><section class="panel"><div class="panel-header"><h3>学习参数</h3><span class="badge purple">${esc(a.name)} 专属</span></div><div class="panel-body">${timingFields(s)}<div class="field-grid"><div class="field"><label for="study-speed">视频倍速</label><input id="study-speed" name="study.speed" type="number" min="1" max="2" step="0.1" value="${s.speed}" required><small>范围 1–2，默认 1 倍。</small></div><div class="field"><label for="study-jobs">并行课程数</label><input id="study-jobs" name="study.jobs" type="number" min="1" max="8" value="${s.jobs}" required><small>同一课程内按章节顺序执行，范围 1–8。</small></div><div class="field"><label for="study-notopen">未开放章节</label><select id="study-notopen" name="study.notopen_action">${[['retry','重试'],['continue','跳过并记录'],['ask','在日志区询问我']].map(([v,l])=>`<option value="${v}" ${s.notopen_action===v?'selected':''}>${l}</option>`).join('')}</select></div><div class="field"><label for="study-interval">重试等待（秒）</label><input id="study-interval" name="study.retry_interval" type="number" min="0.5" max="600" step="0.5" value="${s.retry_interval}" required></div><div class="field"><label for="study-work-retries">章节检测最大重做次数</label><input id="study-work-retries" name="study.work_max_retries" type="number" min="0" max="10" value="${s.work_max_retries}" required></div><div class="field"><label for="study-count">章节学习次数目标</label><input id="study-count" name="study.target_count" type="number" min="1" max="10000" value="${s.target_count}" required></div><div class="field check-field"><input id="study-redo" name="study.work_redo_enabled" type="checkbox" ${s.work_redo_enabled?'checked':''}><label for="study-redo">允许章节检测答错后重做</label></div><div class="field check-field"><input id="study-add-count" name="study.add_learning_count" type="checkbox" ${s.add_learning_count?'checked':''}><label for="study-add-count">任务完成后增加章节学习次数</label></div></div></div></section><section class="panel"><div class="panel-header"><div><h3>题库与 API</h3><p class="subheading">课程目标始终独立；API 可继承全局或为此用户单独设置</p></div></div><div class="panel-body"><div class="check-field"><input type="checkbox" name="inherit_api" id="inherit-api" ${a.config.inherit_api?'checked':''}><label for="inherit-api">使用全局 API 配置</label></div><div class="gap"></div><div id="inherit-notice" class="notice purple ${a.config.inherit_api?'':'hidden'}">此用户当前使用全局配置。下方独立配置会保留，关闭继承后生效。</div><div id="own-api-fields">${apiFields(a.config.api)}</div></div><div class="panel-actions"><small>修改仅影响下次启动的任务</small><button type="submit" class="button primary">保存刷课配置</button></div></section></form>`;
}

function settingsPage() {
  return heading('设置','管理工作空间的全局 API 配置与服务信息。')+
    `<div class="settings-grid"><form id="global-api-form" class="panel"><div class="panel-header"><div><h3>全局 API 配置</h3><p class="subheading">所有开启“使用全局 API 配置”的用户将自动继承</p></div><span class="badge purple">默认配置</span></div><div class="panel-body">${apiFields(state.settings.api)}</div><div class="panel-actions"><small>密钥加密保存，仅返回脱敏信息</small><button type="submit" class="button primary">保存全局配置</button></div></form><aside><section class="panel"><div class="panel-header"><h3>扩展计划</h3><span class="badge">TODO</span></div><div class="panel-body">${state.integrations.map(i=>`<div class="integration"><span class="integration-icon">${icon('link')}</span><div><h3>${esc(i.name)} <span class="badge">待接入</span></h3><p>${esc(i.description)}</p></div></div>`).join('')}</div></section><section class="panel"><div class="panel-header"><h3>服务信息</h3></div><div class="panel-body"><div class="setting-row"><span>当前版本</span><b>${esc(state.system.version)}</b></div><div class="setting-row"><span>会话隔离</span><b>按用户隔离</b></div><div class="setting-row"><span>凭据存储</span><b>本地加密</b></div><div class="setting-row"><span>OCR 扩展</span><b>${state.system.ocr?'已安装':'未安装（可选）'}</b></div><p class="setting-note">第三方推送与 NapCat 当前仅列入计划。登录失效、任务结果等事件已经在“最近动态”中记录。</p></div></section></aside></div>${creditsPanel()}`;
}

function accountsPage() {
  return heading('用户管理','每个用户独立保存会话、学习目标与 API 配置。',button('添加用户','add-account','primary','plus'))+
    `<div class="account-grid">${state.accounts.map(a=>`<article class="account-card"><div class="card-top"><span class="avatar">${esc(a.name.slice(0,1))}</span><span class="badge ${a.status==='active'?'green':'red'}">${a.status==='active'?'已登录':'登录失效'}</span></div><h3>${esc(a.name)}</h3><p>${esc(a.phone||'二维码登录')} · UID ${esc(a.uid)}</p><div class="setting-row"><span>学习目标</span><b>${a.config.course_keys.length} 门课程</b></div><div class="setting-row"><span>API 配置</span><b>${a.config.inherit_api?'继承全局':'独立设置'}</b></div><div class="actions">${button('配置此用户','account-config','secondary small','',`data-id="${a.id}"`)}${button('移除','account-remove','danger small','',`data-id="${a.id}"`)}</div></article>`).join('')}</div>`;
}

function signPage() {
  const a=current(); if(!a) return accountsPage(); const list=state.activities[a.id];
  return heading('签到中心','使用 '+a.name+' 的统一登录会话，读取课程活动。',button('刷新活动','sign-refresh','primary','refresh'))+
    `<div class="notice purple">选择活动后填写所需参数并提交。二维码、位置、图片等按活动要求提供；NapCat 自动获取将在后续版本接入。</div>`+
    (!list?`<section class="panel">${empty('查看当前签到活动','点击“刷新活动”，获取当前用户的有效签到列表。','','sign')}</section>`:!list.length?`<section class="panel">${empty('暂时没有进行中的签到','请确认当前用户，或在老师发布签到后刷新。','','sign')}</section>`:`<div class="sign-grid">${list.map(a=>`<article class="sign-card"><div class="card-top"><span class="course-icon">${icon('sign')}</span><span class="badge ${a.signed?'green':'purple'}">${a.signed?'已签到':esc(kindLabels[a.photo?'photo':a.kind]||'签到活动')}</span></div><h3>${esc(a.title)}</h3><p>${esc(a.course.title)}</p><p>活动编号 ${esc(a.id)}</p>${button(a.signed?'已签到':'填写并签到','sign-open',a.signed?'secondary':'primary','',`data-id="${esc(a.id)}" ${a.signed?'disabled':''}`)}</article>`).join('')}</div>`);
}

function openSign(id) {
  const a=state.activities[state.active]?.find(x=>x.id===id); if(!a) return;
  const kind=a.photo?'photo':a.kind;
  $('#modal-content').innerHTML=`<form id="sign-form" data-activity="${esc(id)}" data-account="${state.active}"><div class="modal-head"><h2>${esc(a.title)}</h2><button type="button" class="icon-button" data-action="modal-close" aria-label="关闭">×</button></div><div class="modal-body"><p class="muted">${esc(a.course.title)} · ${esc(current().name)}</p><div class="field"><label for="sign-kind">签到方式</label><select id="sign-kind" name="kind">${Object.entries(kindLabels).map(([k,l])=>`<option value="${k}" ${kind===k?'selected':''}>${l}</option>`).join('')}</select></div><div class="gap"></div><div id="sign-fields">${signFields(kind)}</div><p class="inline-error" id="sign-error"></p></div><div class="modal-actions"><button type="button" class="button secondary" data-action="modal-close">取消</button><button type="submit" class="button primary">确认提交签到</button></div></form>`;
  $('#modal').showModal();
}

function signFields(kind) {
  const field=(key,label,placeholder='',type='text')=>`<div class="field"><label for="sign-${key}">${label}</label><input id="sign-${key}" name="${key}" type="${type}" placeholder="${placeholder}" required ${type==='number'?'step="any"':''}></div>`;
  if(kind==='qr') return field('qr','当前签到二维码链接 / enc','粘贴学习通签到二维码的解析结果');
  if(kind==='location') return `<div class="field-grid">${field('longitude','经度','如 116.40','number')}${field('latitude','纬度','如 39.90','number')}<div class="field full">${field('address','位置说明','填写当前位置')}</div></div>`;
  if(kind==='photo') return field('object_id','超星云盘图片 objectId','填写已经上传的图片对象 ID')+'<p class="setting-note">初期版本支持已有图片对象 ID，网页直接上传图片列入后续优化。</p>';
  if(kind==='gesture'||kind==='code') return field('code',kind==='gesture'?'手势数字序列':'签到码','输入本次活动提供的数字');
  return '<p class="setting-note">将使用当前用户会话提交此普通签到活动。</p>';
}

function readApi(form) { return Object.fromEntries($$('[name^="api."]',form).map(el=>[el.name.slice(4),el.value])); }

async function saveTargets(id=state.active) {
  const data=await api(`/accounts/${id}/config`,'PUT',{course_keys:[...(state.selection[id]||[])]});
  const a=state.accounts.find(a=>a.id===id); if(a) a.config=data.config;
}

async function loadLogs() {
  if(!state.logJob || !$('#job-logs') || state.logLoading) return;
  state.logLoading=true; const id=state.logJob, box=$('#job-logs');
  try {
    const result=await api(`/jobs/${id}/logs?after=${state.logAfter}`);
    if(state.logJob!==id || $('#job-logs')!==box) return;
    if(!state.logAfter) box.textContent='';
    const bottom=box.scrollHeight-box.scrollTop-box.clientHeight<80;
    for(const line of result.logs) { const el=document.createElement('span'); el.className='log-line '+(line.level==='error'?'error':line.level==='warning'?'warning':''); el.textContent=`${date(line.created_at)}  ${line.message}`; box.append(el); state.logAfter=line.id; }
    if(!box.childNodes.length) box.textContent='等待任务输出…';
    while(box.children.length>2000) box.firstElementChild.remove();
    if(bottom) box.scrollTop=box.scrollHeight;
    updatePrompt();
  } catch(error) { toast(error.message,true); } finally { state.logLoading=false; }
}

function updatePrompt() {
  const container=$('#job-prompt'); if(!container) return;
  const job=state.jobs.find(j=>j.id===state.logJob);
  if(job?.state==='waiting') {
    if(container.dataset.prompt===job.prompt) return;
    container.dataset.prompt=job.prompt;
    container.innerHTML=`<div class="prompt-box"><p>${esc(job.prompt)}</p><form id="job-input-form" data-id="${job.id}"><input name="answer" aria-label="任务交互输入" placeholder="在这里输入回复，支持手动答题"><button class="button primary small" type="submit">发送给任务</button></form></div>`;
  } else { container.innerHTML=''; delete container.dataset.prompt; }
}

async function refreshLive() {
  if(!state.authenticated || state.pollBusy || $('#app-screen').classList.contains('hidden') || document.hidden) return;
  state.pollBusy=true;
  try {
    const data=await api('/jobs'); state.jobs=data.jobs; state.events=data.events; state.accounts=data.accounts;
    if(state.page==='study' && $('#study-jobs')) $('#study-jobs').innerHTML=jobsHTML(state.jobs.filter(j=>j.account_id===state.active));
    if($('#overview-jobs')) $('#overview-jobs').innerHTML=jobsHTML(state.jobs.slice(0,3));
    if($('#overview-events')) $('#overview-events').innerHTML=eventsHTML();
    if(state.page==='study') { await loadLogs(); updatePrompt(); }
  } catch(error) { /* transient background outages do not replace in-progress forms */ }
  finally { state.pollBusy=false; }
}

document.addEventListener('click', async event=>{
  const target=event.target.closest('[data-action]'); if(!target) return;
  const action=target.dataset.action, id=target.dataset.id;
  if(action.startsWith('go-')) return navigate(action.slice(3));
  if(action==='add-account') return showLogin();
  if(action==='modal-close') return $('#modal').close();
  if(action==='sign-open') return openSign(id);
  if(action==='account-config') { state.active=id; syncAccountSwitch(); return navigate('study-config'); }
  if(action==='job-log') { state.logJob=id; state.logAfter=0; navigate('study'); if(state.page==='study') render(); return; }
  if(action==='courses-toggle') { const list=state.courses[state.active]||[]; const selected=state.selection[state.active]; if(!selected) return; const all=list.length&&list.every(c=>selected.has(c.key)); list.forEach(c=>all?selected.delete(c.key):selected.add(c.key)); $('#course-list').innerHTML=coursesHTML($('#course-search').value); $('#selection-count').textContent=selected.size; return; }
  await busy(target,async()=>{
    if(action==='courses-refresh') { const accountId=state.active; const data=await api(`/accounts/${accountId}/courses`); state.courses[accountId]=data.courses; if(accountId===state.active&&$('#course-list')) $('#course-list').innerHTML=coursesHTML($('#course-search')?.value||''); toast(`已读取 ${data.courses.length} 门课程`); }
    if(action==='courses-save') { await saveTargets(); toast('学习目标已保存'); }
    if(action==='study-start') { const accountId=state.active; await saveTargets(accountId); const data=await api(`/accounts/${accountId}/study`,'POST',{}); state.jobs.unshift(data.job); state.logJob=data.job.id; state.logAfter=0; render(); toast('任务已启动，可在日志区查看进度'); }
    if(action==='job-stop') { await api(`/jobs/${id}/stop`,'POST',{}); await refreshLive(); toast('已发送停止请求'); }
    if(action==='sign-refresh') { const accountId=state.active; const data=await api(`/accounts/${accountId}/activities`); state.activities[accountId]=data.activities; if(state.active===accountId&&state.page==='sign') render(); toast(`已读取 ${data.activities.length} 个有效活动`); }
    if(action==='account-remove') { if(!confirm('移除此用户的本地会话与配置？运行中的任务需要先停止。')) return; await api(`/accounts/${id}`,'DELETE',{}); delete state.selection[id]; await bootstrap(); toast('已移除用户'); }
  });
});

document.addEventListener('change',event=>{
  if(event.target.id==='study-mode') $('#timing-notice').textContent=timingNotice(event.target.value==='duration');
  if(event.target.dataset.course) { const set=state.selection[state.active]; if(event.target.checked) set.add(event.target.dataset.course); else set.delete(event.target.dataset.course); $('#selection-count').textContent=set.size; }
  if(event.target.id==='inherit-api') $('#inherit-notice').classList.toggle('hidden',!event.target.checked);
  if(event.target.id==='sign-kind') $('#sign-fields').innerHTML=signFields(event.target.value);
});
document.addEventListener('input',event=>{ if(event.target.id==='course-search') $('#course-list').innerHTML=coursesHTML(event.target.value); });

document.addEventListener('submit',async event=>{
  const form=event.target; if(!['global-api-form','study-config-form','sign-form','job-input-form'].includes(form.id)) return;
  event.preventDefault(); const accountId=state.active;
  await busy($('button[type="submit"]',form), async()=>{
    if(form.id==='global-api-form') { const data=await api('/settings','PUT',{api:readApi(form)}); state.settings=data; toast('全局 API 配置已保存'); render(); }
    if(form.id==='study-config-form') { const study=Object.fromEntries($$('[name^="study."]',form).map(el=>[el.name.slice(6),el.type==='checkbox'?el.checked:el.type==='number'?Number(el.value):el.value])); const data=await api(`/accounts/${accountId}/config`,'PUT',{study,inherit_api:$('#inherit-api').checked,api:readApi(form)}); const a=state.accounts.find(a=>a.id===accountId); if(a) a.config=data.config; toast('用户刷课配置已保存'); render(); }
    if(form.id==='sign-form') { const payload=Object.fromEntries(new FormData(form)); payload.activity_id=form.dataset.activity; try{ const data=await api(`/accounts/${form.dataset.account}/sign`,'POST',payload); const activity=state.activities[form.dataset.account]?.find(a=>a.id===payload.activity_id); if(activity) activity.signed=true; $('#modal').close(); toast(data.message); render(); }catch(error){ $('#sign-error').textContent=error.message; throw error; } }
    if(form.id==='job-input-form') { await api(`/jobs/${form.dataset.id}/input`,'POST',{answer:form.elements.answer.value}); toast('回复已发送'); await refreshLive(); }
  },'正在保存 / 提交…');
});

$('#password-form').addEventListener('submit',async event=>{
  event.preventDefault(); const btn=$('button[type="submit"]',event.target); $('#login-error').textContent='';
  await busy(btn,async()=>{ try{ await afterLogin(await api('/auth/password','POST',{phone:$('#phone').value,password:$('#password').value})); }catch(error){ $('#login-error').textContent=error.message; throw error; } },'正在登录…');
});
$('#toggle-password').onclick=()=>{ const input=$('#password'); input.type=input.type==='password'?'text':'password'; $('#toggle-password').textContent=input.type==='password'?'显示':'隐藏'; };
$('#password-tab').onclick=()=>{ stopQR(); $('#password-tab').classList.add('selected'); $('#qr-tab').classList.remove('selected'); $('#password-tab').setAttribute('aria-selected','true'); $('#qr-tab').setAttribute('aria-selected','false'); $('#password-form').classList.remove('hidden'); $('#qr-panel').classList.add('hidden'); $('#login-error').textContent=''; };
$('#qr-tab').onclick=()=>{ $('#qr-tab').classList.add('selected'); $('#password-tab').classList.remove('selected'); $('#qr-tab').setAttribute('aria-selected','true'); $('#password-tab').setAttribute('aria-selected','false'); $('#password-form').classList.add('hidden'); $('#qr-panel').classList.remove('hidden'); $('#login-error').textContent=''; startQR(); };
$('#refresh-qr').onclick=()=>busy($('#refresh-qr'),startQR,'正在刷新…');
$('#cancel-login').onclick=()=>{ stopQR(); $('#login-screen').classList.add('hidden'); $('#app-screen').classList.remove('hidden'); render(); };
$('#add-account').onclick=showLogin;
$('#account-switch').onchange=event=>{ state.active=event.target.value; state.logJob=null; state.logAfter=0; syncAccountSwitch(); render(); };
$('#logout').onclick=()=>busy($('#logout'),async()=>{ await api('/auth/logout','POST',{}); stopQR(); state.authenticated=false; state.accounts=[]; state.active=''; state.selection={}; state.courses={}; state.activities={}; state.logJob=null; const data=await api('/session'); state.csrf=data.csrf; showLogin(); });
window.addEventListener('hashchange',()=>{state.logAfter=0;render();});
setInterval(refreshLive,3000);

(async()=>{
  try { const data=await api('/session'); state.csrf=data.csrf; state.authenticated=data.authenticated; if(data.authenticated) await bootstrap(); else showLogin(); }
  catch(error) { $('#loading').textContent='无法连接后台：'+error.message+'。请确认服务已启动后刷新。'; }
})();
