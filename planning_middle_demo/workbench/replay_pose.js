/* Display-only interpolation of recorded poses; never changes simulation or commands. */
(() => {
  const cache = new WeakMap();
  const terminal = p => ['succeeded', 'failed', 'cancelled', 'lost'].includes(p?.status) || p?.lost;
  function sameSegment(a,b) {
    return a.command === b.command && a.job === b.job && a.phase === b.phase &&
      a.status === b.status && !terminal(a) && !terminal(b);
  }
  function samePose(a,b) {
    return ['x','y','z','yaw'].every(key => a[key] === b[key]);
  }
  function samples(worker) {
    const raw=worker.samples || [];
    if(!['PLANE','WING'].includes(worker.kind))return raw;
    const saved=cache.get(worker);
    if(saved && saved.raw===raw && saved.length===raw.length && saved.tail===raw.at(-1))return saved.display;
    const display=[];
    for(let i=0;i<raw.length;) {
      let end=i;
      while(end+1<raw.length && sameSegment(raw[i],raw[end+1]) && samePose(raw[i],raw[end+1]))end++;
      const next=raw[end+1];
      // Discrete behavior targets can reach their next point in the first 0.1 s
      // and repeat it for the other nine substeps. Recover the display keyframes
      // without changing observed positions, paths, or command boundaries.
      const cadence=next && next.t-raw[i].t;
      const plateau=end>i && cadence>0 && cadence<=1.01 &&
        sameSegment(raw[i],next) && !samePose(raw[i],next);
      if(plateau)display.push(raw[i]);
      else for(let n=i;n<=end;n++)display.push(raw[n]);
      i=end+1;
    }
    cache.set(worker,{raw,length:raw.length,tail:raw.at(-1),display});
    return display;
  }
  function between(previous, next, time) {
    const result = {...previous};
    if (!previous || !next || !Number.isFinite(time) ||
        !Number.isFinite(previous.t) || !Number.isFinite(next.t) ||
        next.t <= previous.t || previous.command !== next.command ||
        ['succeeded', 'failed', 'cancelled', 'lost'].includes(previous.status)) return result;
    const fraction = Math.max(0, Math.min(1, (time - previous.t) / (next.t - previous.t)));
    for (const field of ['x', 'y', 'z']) {
      if (Number.isFinite(previous[field]) && Number.isFinite(next[field])) {
        result[field] = previous[field] + (next[field] - previous[field]) * fraction;
      }
    }
    if (Number.isFinite(previous.yaw) && Number.isFinite(next.yaw)) {
      // Crossing +pi/-pi must rotate through the short arc, not a full circle.
      const delta = Math.atan2(Math.sin(next.yaw - previous.yaw),
                               Math.cos(next.yaw - previous.yaw));
      result.yaw = previous.yaw + delta * fraction;
    }
    return result;
  }
  // Clip recorded movement by simulation time, including a partly played edge.
  // A sparse recording can have no sample inside the window while the agent
  // is still moving between two samples. Keep that edge instead of losing it.
  function trails(raw, time, {seconds=10, full=false, interpolate=true, current=null}={}) {
    const cutoff=full?0:Math.max(0,time-seconds), result=[];
    const valid=p=>p&&['t','x','y'].every(key=>Number.isFinite(p[key]));
    const continuous=(a,b)=>a.command===b.command&&a.job===b.job&&!terminal(a);
    let lo=0,hi=raw.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(raw[mid].t<cutoff)lo=mid+1;else hi=mid;}
    let segment=[],previous=null;
    const flush=()=>{if(segment.length>1&&segment.some(p=>Math.hypot(p.x-segment[0].x,p.y-segment[0].y)>.001))result.push(segment);segment=[];};
    const add=point=>{
      if(!valid(point)){flush();previous=null;return;}
      if(previous&&!continuous(previous,point)){flush();previous=null;}
      if(point.t>=cutoff){
        if(previous&&previous.t<cutoff&&point.t>cutoff&&interpolate&&!terminal(previous))segment.push({...between(previous,point,cutoff),t:cutoff});
        segment.push(point);
      }
      previous=point;
    };
    let index=Math.max(0,lo-1);
    for(;index<raw.length&&raw[index].t<=time;index++)add(raw[index]);
    const next=raw[index];
    if(previous&&time>previous.t){
      if(interpolate&&valid(next)&&continuous(previous,next)&&!terminal(previous))add({...between(previous,next,time),t:time});
      else if(valid(current)&&continuous(previous,current))add({...current,t:time});
    }
    flush();return result;
  }
  window.ReplayPose = Object.freeze({between,samples,trails});
})();
