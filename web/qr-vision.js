/* Capture and draw only. All QR recognition and signing run on the server. */
(function(root,factory){
  const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.QRVision=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function constraints(facing='environment'){
    return {audio:false,video:{facingMode:{ideal:facing},width:{ideal:1920},height:{ideal:1080},frameRate:{ideal:24,max:30}}};
  }
  async function focus(track){
    try{
      const caps=track?.getCapabilities?.()||{},advanced={};
      if(caps.focusMode?.includes('continuous'))advanced.focusMode='continuous';
      if(caps.exposureMode?.includes('continuous'))advanced.exposureMode='continuous';
      if(Object.keys(advanced).length)await track.applyConstraints({advanced:[advanced]});
    }catch{}
  }
  async function jpeg(video,canvas,context){
    const scale=Math.min(1,1920/Math.max(video.videoWidth,video.videoHeight));
    const width=Math.max(1,Math.round(video.videoWidth*scale)),height=Math.max(1,Math.round(video.videoHeight*scale));
    if(canvas.width!==width)canvas.width=width;if(canvas.height!==height)canvas.height=height;
    context.drawImage(video,0,0,width,height);
    const encode=quality=>new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('无法编码摄像头画面')),'image/jpeg',quality));
    let blob=await encode(.85);
    if(blob.size>768*1024)blob=await encode(.55);
    if(blob.size>768*1024)throw new Error('视频帧过大，请调整镜头后重试');
    return blob;
  }
  function outline(svg,result){
    if(!svg?.setAttribute)return;
    const points=result?.corners,width=result?.width,height=result?.height;
    if(!Array.isArray(points)||points.length!==4||!width||!height||points.some(p=>!Number.isFinite(p.x)||!Number.isFinite(p.y)||p.x<0||p.y<0||p.x>width||p.y>height)){
      svg.setAttribute('hidden','');return;
    }
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('data-decoded',result.decoded?'true':'false');
    svg.querySelector('polygon')?.setAttribute('points',points.map(p=>`${p.x},${p.y}`).join(' '));svg.removeAttribute('hidden');
  }
  return {constraints,focus,jpeg,outline};
});
