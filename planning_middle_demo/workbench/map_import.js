/* Geometry-only map import. Never creates a task, run or planner constraint. */
(() => {
  'use strict';
  let map=null,view=null,drag=null,host,surface,context,summary,picker;
  const el=(tag,text)=>{const node=document.createElement(tag);if(text)node.textContent=text;return node;};
  function validate(data){
    const point=p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);
    if(!data||data.schema!=='neutral-urban-map/v1'||data.units!=='m')throw Error('请选择纯地图 map.json，不能导入任务 JSON 或桌面运行配置。');
    const b=data.bounds;
    if(!Array.isArray(b)||b.length!==4||!b.every(Number.isFinite)||b[2]<=b[0]||b[3]<=b[1])throw Error('地图边界无效');
    for(const [key,limit] of [['nodes',10000],['roads',10000],['buildings',10000],['parks',2000],['trees',20000],['obstacles',10000]]){
      if(!Array.isArray(data[key])||data[key].length>limit)throw Error('地图集合无效：'+key);
    }
    if(!data.nodes.every(point)||!data.trees.every(point))throw Error('地图坐标无效');
    for(const r of data.roads){if(![r.a,r.b].every(i=>Number.isInteger(i)&&i>=0&&i<data.nodes.length)||!Number.isFinite(r.width_m)||r.width_m<=0)throw Error('道路索引或宽度无效');}
    for(const k of ['buildings','parks','obstacles'])for(const item of data[k]){
      if(!Array.isArray(item.box)||item.box.length!==4||!item.box.every(Number.isFinite)||item.box[2]<=0||item.box[3]<=0)throw Error('地图几何无效：'+k);
    }
    return data;
  }
  function projection(){
    const w=surface.clientWidth,h=surface.clientHeight,[x0,y0,x1,y1]=view;
    const scale=Math.min((w-50)/(x1-x0),(h-50)/(y1-y0));
    return {scale,point:p=>[w/2+(p[0]-(x0+x1)/2)*scale,h/2-(p[1]-(y0+y1)/2)*scale]};
  }
  function draw(){
    if(!map||!surface.clientWidth)return;
    const ratio=devicePixelRatio||1,w=surface.clientWidth,h=surface.clientHeight;
    surface.width=Math.round(w*ratio);surface.height=Math.round(h*ratio);context.setTransform(ratio,0,0,ratio,0,0);
    context.fillStyle='#eeeee7';context.fillRect(0,0,w,h);const p=projection();
    function box(values,fill,stroke){const [x,y,bw,bh]=values,[px,py]=p.point([x-bw/2,y+bh/2]);context.fillStyle=fill;context.fillRect(px,py,bw*p.scale,bh*p.scale);if(stroke){context.strokeStyle=stroke;context.lineWidth=.7;context.strokeRect(px,py,bw*p.scale,bh*p.scale);}}
    for(const park of map.parks)box(park.box,'#d3e3c8','#b4c7a7');
    for(const tree of map.trees){const [x,y]=p.point(tree);context.beginPath();context.arc(x,y,Math.max(1,2.4*p.scale),0,Math.PI*2);context.fillStyle='#a4bd96';context.fill();}
    context.lineCap='square';for(const r of map.roads){const a=p.point(map.nodes[r.a]),b=p.point(map.nodes[r.b]);context.beginPath();context.moveTo(...a);context.lineTo(...b);context.strokeStyle='#d0d2ca';context.lineWidth=r.width_m*p.scale+1.5;context.stroke();context.strokeStyle='#fcfcf7';context.lineWidth=r.width_m*p.scale;context.stroke();}
    for(const b of map.buildings){box([b.box[0]+2,b.box[1]-2,b.box[2],b.box[3]],'#00000012');box(b.box,b.category==='办公'?'#c3cbd2':b.category==='商铺'?'#d7ccbf':'#d0d2c9','#a8b2ad');}
    for(const b of map.obstacles)box(b.box,'#8c938b','#717b72');
    context.font='12px Microsoft YaHei';context.fillStyle='#496653';context.fillText('北 ↑',18,25);
    const length=10**Math.floor(Math.log10(130/p.scale));context.fillText(length+' m',18,h-28);context.strokeStyle='#496653';context.lineWidth=2;context.beginPath();context.moveTo(18,h-20);context.lineTo(18+length*p.scale,h-20);context.stroke();
  }
  function close(){if(!map)return;map=null;host.hidden=true;document.body.classList.remove('map-import-mode');picker.value='';window.dispatchEvent(new Event('resize'));}
  function open(data){
    validate(data);setPlaying(false);closeTheater();setPage('overview');showOverviewMode('map');
    map=data;view=data.bounds.slice();host.hidden=false;document.body.classList.add('map-import-mode');
    summary.textContent=String(data.label||data.id)+' · '+(data.bounds[2]-data.bounds[0])+' × '+(data.bounds[3]-data.bounds[1])+' 米 · '+data.buildings.length+' 栋建筑 · '+data.roads.length+' 段道路 · '+data.obstacles.length+' 处障碍';
    requestAnimationFrame(draw);
  }
  async function loadPreset(id){try{const r=await fetch('/api/maps/'+encodeURIComponent(id));if(!r.ok)throw Error('地图读取失败，请重新启动工作台');open(await r.json());picker.value=id;}catch(e){toast(e.message);}}
  function init(){
    if(new URLSearchParams(location.search).get('desktop')==='1')return;
    const style=el('style');style.textContent=`
      #map-import-controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}#map-import-controls select{max-width:220px}
      #imported-map-host[hidden]{display:none!important}#imported-map-host{padding:14px;min-width:0}
      #imported-map-host header{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding-bottom:12px}#imported-map-host strong{flex:1}
      #imported-map-canvas{display:block;width:100%;height:clamp(400px,68vh,850px);background:#eeeee7;touch-action:none;cursor:grab}
      #imported-map-host p{color:#61776a;font-size:13px;margin:12px 0 0}
      body.map-import-mode .map-card>:not(#imported-map-host),body.map-import-mode .stats,body.map-import-mode .right-column,body.map-import-mode .layout-splitter,body.map-import-mode #behavior-panel,body.map-import-mode .event-card,body.map-import-mode #layout-actions,body.map-import-mode #layout-events,body.map-import-mode .run-choice,body.map-import-mode .run-right>:not(#map-import-controls){display:none!important}
      body.map-import-mode .overview-grid{grid-template-columns:minmax(0,1fr)!important}
    `;document.head.append(style);
    const controls=el('div');controls.id='map-import-controls';picker=el('select');picker.id='map-import-select';picker.setAttribute('aria-label','选择城市地图');picker.add(new Option('选择城市地图…',''));picker.onchange=()=>{if(picker.value)loadPreset(picker.value);};
    const choose=el('button','导入地图…');choose.className='button';choose.id='import-map-file';
    const input=el('input');input.type='file';input.accept='.json,application/json';input.id='map-import-file';input.hidden=true;
    choose.onclick=()=>{input.value='';input.click();};input.onchange=async()=>{try{const f=input.files[0];if(!f)return;if(f.size>10*1024*1024)throw Error('地图文件超过 10 MB');const data=JSON.parse((await f.text()).replace(/^\uFEFF/,''));open(data);picker.value='';}catch(e){toast('导入失败：'+e.message);}};
    controls.append(picker,choose,input);document.querySelector('.run-right').append(controls);
    host=el('section');host.id='imported-map-host';host.hidden=true;const header=el('header');summary=el('strong');const fit=el('button','显示完整地图');fit.className='button small';fit.onclick=()=>{view=map.bounds.slice();draw();};const back=el('button','返回运行视图');back.className='button small';back.id='close-imported-map';back.onclick=close;header.append(summary,fit,back);
    surface=el('canvas');surface.id='imported-map-canvas';surface.setAttribute('aria-label','导入的城市地图，仅显示静态几何');context=surface.getContext('2d');
    host.append(header,surface,el('p','只读地图 · 建筑、道路、公园与路侧障碍。滚轮缩放，拖动平移。地图导入不创建任务、规划约束或执行记录；未运行算法。'));
    document.querySelector('.map-card').append(host);
    surface.onwheel=e=>{if(!map)return;e.preventDefault();const rect=surface.getBoundingClientRect(),p=projection(),[x0,y0,x1,y1]=view,cx=(x0+x1)/2,cy=(y0+y1)/2;
      const x=cx+(e.clientX-rect.left-rect.width/2)/p.scale,y=cy-(e.clientY-rect.top-rect.height/2)/p.scale,f=Math.exp(Math.max(-150,Math.min(150,e.deltaY))*.006);
      if((x1-x0)*f<10||(x1-x0)*f>Math.max(...map.bounds)*20)return;view=[x+(x0-x)*f,y+(y0-y)*f,x+(x1-x)*f,y+(y1-y)*f];draw();};
    surface.onpointerdown=e=>{if(e.button!==0)return;drag=[e.clientX,e.clientY,view.slice()];surface.setPointerCapture(e.pointerId);};surface.onpointermove=e=>{if(!drag)return;const p=projection(),dx=(e.clientX-drag[0])/p.scale,dy=(e.clientY-drag[1])/p.scale;view=[drag[2][0]-dx,drag[2][1]+dy,drag[2][2]-dx,drag[2][3]+dy];draw();};for(const event of ['pointerup','pointercancel','lostpointercapture'])surface.addEventListener(event,()=>drag=null);
    new ResizeObserver(draw).observe(surface);
    document.addEventListener('click',e=>{if(map&&e.target.closest('.nav,[data-goto]'))close();},true);
    document.getElementById('run-select').addEventListener('change',close);
    fetch('/api/maps').then(r=>{if(!r.ok)throw Error('地图目录未就绪');return r.json();}).then(items=>{for(const item of items)picker.add(new Option(item.label,item.id));}).catch(()=>{picker.options[0].text='目录不可用，可导入 map.json';});
    const requested=new URLSearchParams(location.search).get('map');if(requested){let n=0;const timer=setInterval(()=>{if(state.catalog&&(state.run||!state.catalog.runs.length)){clearInterval(timer);loadPreset(requested);}else if(++n>100){clearInterval(timer);toast('请先确认工作台服务已连接，再选择城市地图。');}},100);}
  }
  window.WorkbenchMaps={open,close,validate,active:()=>!!map,document:()=>map};
  document.addEventListener('DOMContentLoaded',init);
})();
