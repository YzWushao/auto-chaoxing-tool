const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const events={},nodes={},calls=[];
const node=id=>nodes[id]??={innerHTML:'',textContent:'',value:'',hidden:true,focus(){},select(){}};
const ctx=vm.createContext({console,Date,Object,Number,String,Set,
  state:{},esc:value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  $:selector=>node(selector),document:{addEventListener:(name,fn)=>events[name]=fn},
  navigator:{clipboard:{writeText:async value=>calls.push(['copy',value])}},toast:()=>{},busy:async(button,fn)=>fn(),
  api:async(path,method,body)=>{
    calls.push([path,method,body]);
    return path==='/access/keys'?{token:'synthetic-key-only-once'}:{enabled:true,keys:[],audit:[],scopes:{read:'Read','sign:write':'Sign'}};
  }
});
const run=code=>vm.runInContext(code,ctx);run(fs.readFileSync('web/api-access.js','utf8'));
(async()=>{
 const html=run(`apiAccessContent({enabled:false,keys:[{name:'<script>bad</script>',prefix:'act_test',scopes:['read'],expires_at:1,revoked:false,rate_limit:600}],audit:[],scopes:{read:'Read','sign:write':'Sign'}})`);
 assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;'));assert(html.includes('/api/access/openapi.json'));
 assert(!html.includes('name="enabled" checked'));assert(html.includes('name="scopes" value="read" checked'));
 const form={id:'api-key-create',elements:{name:{value:'Bot'},expires_days:{value:'90'},rate_limit:{value:'600'}},
  querySelector:()=>({}),querySelectorAll:()=>[{value:'read'},{value:'sign:write'}]};
 await events.submit({target:form,preventDefault(){}});
 assert.equal(node('#api-key-secret').value,'synthetic-key-only-once');assert.equal(node('#api-key-created').hidden,false);
 assert(!node('#api-access-content').innerHTML.includes('synthetic-key-only-once'));
 assert.equal(Object.keys(ctx.state).length,0,'Never retain the plaintext key in application state');
 await events.click({target:{closest:()=>({id:'api-key-copy'})}});
 assert.deepEqual(calls.at(-1),['copy','synthetic-key-only-once']);
 await events.click({target:{closest:()=>({id:'api-key-hide'})}});
 assert.equal(node('#api-key-secret').value,'');assert.equal(node('#api-key-created').hidden,true);
 console.log('API scope rendering and one-time secret copy/hide lifecycle verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
