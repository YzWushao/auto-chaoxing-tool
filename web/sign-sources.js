'use strict';
function currentSignSource() {return state.page==='sign-group'&&state.preferences?.include_group_sign?'group':'course';}
function signActivityKey(accountId,source=currentSignSource()) {return source==='group'?accountId+':group':accountId;}
function signSourceTabs() {
  const source=currentSignSource();
  return `<div class="actions"><a class="button ${source==='course'?'primary':'secondary'} small" href="#sign">课程签到</a>${state.preferences?.include_group_sign?`<a class="button ${source==='group'?'primary':'secondary'} small" href="#sign-group">群聊签到</a>`:''}</div><div class="gap"></div>`;
}
function signWarnings(key) {return (state.signWarnings?.[key]||[]).map(message=>`<div class="notice" role="alert">${esc(message)}</div>`).join('');}
