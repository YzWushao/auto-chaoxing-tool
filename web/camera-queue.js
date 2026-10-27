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
    constructor(accounts){
      this.entries=[...new Map(accounts.map(a=>[a.id,{id:a.id,name:a.name,status:'pending',attempts:0,failures:0,passFailures:0,rotations:0,message:'等待扫码'}])).values()];
      this.order=this.entries.map(a=>a.id);this.activityId='';this.inFlight=null;
    }
    get current(){return this.entries.find(a=>a.id===this.order[0]);}
    get done(){return this.order.length===0;}
    bind(id){if(!this.activityId)this.activityId=id;return this.activityId===id;}
    begin(){
      if(this.inFlight||this.done)return null;
      const entry=this.current;entry.attempts++;entry.status='submitting';this.inFlight=entry;return entry;
    }
    finish(success,message){
      const entry=this.inFlight;if(!entry)return null;
      this.inFlight=null;entry.message=message;
      if(success){entry.status='succeeded';this.order.shift();}
      else{
        entry.status='pending';entry.failures++;entry.passFailures++;
        if(entry.passFailures>10){this.order.push(this.order.shift());entry.passFailures=0;entry.rotations++;return {entry,moved:true};}
      }
      return {entry,moved:false};
    }
    defer(message){
      const entry=this.inFlight;if(!entry)return;
      entry.attempts--;entry.status='pending';entry.message=message;this.inFlight=null;
    }
    rows(){return [...this.order.map(id=>this.entries.find(a=>a.id===id)),...this.entries.filter(a=>a.status==='succeeded')];}
  }
  return {Queue,parameters};
});
