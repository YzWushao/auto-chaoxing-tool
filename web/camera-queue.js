/* Independently implemented queue rules; no camera, network, or storage access. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.SignCameraQueue=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function parameters(raw){
    if(typeof raw!=='string'||raw.length>4096)return null;
    try{
      raw=raw.trim();
      const query=raw.startsWith('SIGNIN:')?new URLSearchParams(raw.slice(7).split('-')[0]):new URL(raw).searchParams;
      const activityId=query.get('id')||query.get('aid')||query.get('activeId')||query.get('activePrimaryId')||'';
      const enc=query.get('enc')||'';
      return /^[1-9][0-9]{0,24}$/.test(activityId)&&/^[A-Za-z0-9_-]{8,256}$/.test(enc)?{raw,activityId}:null;
    }catch{return null;}
  }
  class Queue{
    constructor(accounts,concurrency=1){
      this.entries=[...new Map(accounts.map(a=>[a.id,{id:a.id,name:a.name,status:'pending',attempts:0,failures:0,passFailures:0,rotations:0,retryAt:0,message:'等待扫码'}])).values()];
      this.order=this.entries.map(a=>a.id);this.activityId='';this.inFlight=new Map();
      this.concurrency=Number.isInteger(concurrency)?Math.max(1,Math.min(5,concurrency)):1;
    }
    get current(){return this.entries.find(a=>a.id===this.order[0]);}
    get done(){return this.order.length===0;}
    bind(id){if(!this.activityId)this.activityId=id;return this.activityId===id;}
    focus(id){
      if(this.order.includes(id))this.order=[id,...this.order.filter(value=>value!==id)];
    }
    begin(id=null,now=Infinity){
      if(this.inFlight.size>=this.concurrency||this.done)return null;
      const entry=this.order.slice(0,this.concurrency).map(value=>this.entries.find(a=>a.id===value)).find(a=>(id===null||a.id===id)&&a.status==='pending'&&a.retryAt<=now);
      if(!entry)return null;
      entry.attempts++;entry.status='submitting';this.inFlight.set(entry.id,entry);return entry;
    }
    finish(success,message,id=null){
      const entry=id===null?this.inFlight.values().next().value:this.inFlight.get(id);if(!entry)return null;
      this.inFlight.delete(entry.id);entry.message=message;
      if(success){entry.status='succeeded';this.order=this.order.filter(value=>value!==entry.id);}
      else{
        entry.status='pending';entry.failures++;entry.passFailures++;
        if(entry.passFailures>10){this.order=this.order.filter(value=>value!==entry.id);this.order.push(entry.id);entry.passFailures=0;entry.rotations++;return {entry,moved:true};}
      }
      return {entry,moved:false};
    }
    defer(message,id=null){
      const entry=id===null?this.inFlight.values().next().value:this.inFlight.get(id);if(!entry)return;
      entry.attempts--;entry.status='pending';entry.message=message;this.inFlight.delete(entry.id);
    }
    confirm(id,message){
      const entry=this.entries.find(a=>a.id===id);
      if(!entry||this.inFlight.has(id)||!this.order.includes(id))return false;
      entry.status='succeeded';entry.message=message;this.order=this.order.filter(value=>value!==id);return true;
    }
    rows(){return [...this.order.map(id=>this.entries.find(a=>a.id===id)),...this.entries.filter(a=>a.status==='succeeded')];}
  }
  return {Queue,parameters};
});
