'use strict';
function currentSignSource() {return 'course';}
function signActivityKey(accountId,source=currentSignSource()) {return source==='group'?accountId+':group':accountId;}
function signSourceTabs() {
  return '<div class="actions"><a class="button primary small" href="#sign">课程签到</a></div><div class="gap"></div>';
}
function signWarnings(key) {return (state.signWarnings?.[key]||[]).map(message=>`<div class="notice" role="alert">${esc(message)}</div>`).join('');}
