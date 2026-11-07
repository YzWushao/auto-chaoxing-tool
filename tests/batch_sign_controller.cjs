const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const events={},requests=[],nodes=new Map();
const element=id=>nodes.get(id)||null;
const context=vm.createContext({console,Set,Map,Promise,JSON,encodeURIComponent,
  state:{authenticated:true,page:'sign',accounts:[{id:'a',name:'张 1234',status:'active'},{id:'b',name:'李 5678',status:'active'},{id:'c',name:'失效',status:'expired'}],location_presets:[]},
  window:{},document:{getElementById:element,addEventListener:(name,fn)=>events[name]=fn},
  esc:String,setTimeout:()=>1,clearTimeout(){},api:async(path,method,data)=>{requests.push({path,data});return {id:'offline',terminal:true,accounts:[]};}});
vm.runInContext(fs.readFileSync('web/batch-sign.js','utf8'),context);
const run=source=>vm.runInContext(source,context);
(async()=>{
  const html=run('bulkSignPanel()');
  for(const mode of ['二维码扫描','定位签到','手势 / 签到码','普通签到','全选所有可用用户'])assert(html.includes(mode));
  assert(!html.includes('overflow'));
  assert.equal(requests.length,0,'Rendering never submits attendance');
  assert.equal(run('bulkUsers().length'),2);
  const groups=run(`bulkAggregate([{user:state.accounts[0],activities:[{id:'901',kind:'normal',title:'common',course:{title:'course'},signed:false},{id:'902',kind:'location',title:'other',course:{title:'course'}}]},
    {user:state.accounts[1],activities:[{id:'901',kind:'normal',title:'common',course:{title:'course'},signed:true}]}])`);
  assert.equal(groups[0].id,'901');assert.equal(groups[0].targets.length,2);assert.equal(groups[0].targets[0].name,'张 1234');
  run(`bulkSign.groups=[{key:'gesture',id:'901',kind:'gesture',phase:'in',targets:[{id:'a',name:'one',signed:false},{id:'b',name:'two',signed:true}]}];bulkSign.group='gesture';bulkSign.code='00123'`);
  await run('bulkStart()');
  assert.deepEqual(JSON.parse(JSON.stringify(requests[0].data)),{account_ids:['a'],activity_id:'901',kind:'gesture',phase:'in',code:'00123'});
  run(`bulkSign.selected=new Set(['b']);bulkSign.all=false`);assert.equal(run('bulkUsers()[0].id'),'b');
  run('resetBulkSign()');assert.equal(run('bulkSign.code'),'');assert.equal(run('bulkSign.run'),null);
  console.log('Bulk modes, global nicknames, eligible users, explicit activity and code verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
