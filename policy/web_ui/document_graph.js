// 图形布局不产生新的业务关系，原文内容一律通过 textContent 展示。
const data = JSON.parse(document.getElementById('graph-data').textContent);
const nodes = new Map(data.nodes.map(node => [node.id, node]));
const typeName = {cites:'引用', mentions:'提及', abolishes:'废止'};
const stateName = {approved:'已审核', pending:'待审核', machine_extracted:'机器识别'};
const resolutionName = {resolved:'已匹配入库文件', ambiguous:'版本不明确', not_in_corpus:'未匹配入库文件'};
const validityName = {current:'当前有效记录', invalid:'失效记录', unknown:'效力待核实'};
const degree = new Map();
// 被引量按不同来源文件计数，同一文件的多处引用只计一次，不混入提及和废止。
const citingSources=new Map();
for(const edge of data.edges) if(edge.type==='cites') {
  if(!citingSources.has(edge.target)) citingSources.set(edge.target,new Set());
  citingSources.get(edge.target).add(edge.source);
}
const maxCitations=Math.max(1,...[...citingSources.values()].map(sources=>sources.size));
function citationCount(id){return citingSources.get(id)?.size||0;}
function citationStrength(id){return Math.log1p(citationCount(id))/Math.log1p(maxCitations);}
// 使用对数缩放并限制最大半径，突出高被引文件，同时保持节点之间留白。
function overviewNodeRadius(id){return 5+9*citationStrength(id);}
for (const edge of data.edges) {
  degree.set(edge.source, (degree.get(edge.source)||0)+1);
  degree.set(edge.target, (degree.get(edge.target)||0)+1);
}
let focus = [...data.nodes].sort((a,b)=>(degree.get(b.id)||0)-(degree.get(a.id)||0)).find(n=>n.policy_id)?.id || data.nodes[0]?.id;
let currentView = 'global';
let camera = {x:0, y:0, scale:1};
let worldBounds = {width:1200, height:700};
let viewport = null;
const svg = document.getElementById('graph');
const ns = 'http://www.w3.org/2000/svg';

function el(name,text,parent,cls) {
  const element=document.createElement(name);
  if(text!==undefined) element.textContent=text;
  if(cls) element.className=cls;
  if(parent) parent.appendChild(element);
  return element;
}
function sv(name,attrs,parent) {
  const element=document.createElementNS(ns,name);
  for(const [key,value] of Object.entries(attrs)) element.setAttribute(key,value);
  parent.appendChild(element); return element;
}
function dash(edge) {return edge.type==='mentions'?'2 5':edge.review_status==='pending'?'7 5':'';}
function edgeColor(edge) {return edge.type==='abolishes'?'#c62828':'#002fa7';}
function edgeMarker(edge) {return edge.type==='abolishes'?'url(#arrow-abolishes)':'url(#arrow)';}
function overviewEdgeStyle(edge) {
  if(edge.type==='abolishes') return {opacity:0.85,width:1.8};
  if(edge.type==='mentions') return {opacity:0.16,width:0.8};
  const strength=citationStrength(edge.target);
  return {opacity:0.14+strength*0.66,width:0.7+strength*1.9};
}
function highlightOverview(id=null) {
  for(const path of viewport.querySelectorAll('.global-edge')) {
    const related=path.dataset.source===id||path.dataset.target===id;
    path.style.opacity=id&&!related?'0.06':'1';
    path.setAttribute('stroke-opacity',related?1:path.dataset.baseOpacity);
    path.setAttribute('stroke-width',related?Math.min(3.6,Number(path.dataset.baseWidth)+0.9):path.dataset.baseWidth);
  }
}
function addMarker() {
  const defs=sv('defs',{},svg);
  for(const [id,color] of [['arrow','#002fa7'],['arrow-abolishes','#c62828']]) {
    const marker=sv('marker',{id,viewBox:'0 0 10 10',refX:10,refY:5,markerWidth:8,markerHeight:8,orient:'auto'},defs);
    sv('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:color},marker);
  }
}
function visibleEdges() {
  return data.edges.filter(edge=>(edge.type!=='mentions'||document.getElementById('show-mentions').checked)
    &&(edge.type!=='abolishes'||edge.review_status!=='pending'||document.getElementById('show-pending').checked));
}
function showList() {
  const list=document.getElementById('documents'); list.replaceChildren();
  const query=document.getElementById('search').value.trim().toLowerCase();
  const found=data.nodes.filter(n=>(n.title+' '+(n.doc_number||'')).toLowerCase().includes(query))
    .sort((a,b)=>(degree.get(b.id)||0)-(degree.get(a.id)||0));
  document.getElementById('list-count').textContent=`匹配 ${found.length} 个节点，列出前 120 个；点击进入局部图`;
  for(const node of found.slice(0,120)) {
    const button=el('button',node.title,list,'document'+(node.id===focus&&currentView==='local'?' selected':''));
    el('div',(node.doc_number||'文号未明确')+' · '+resolutionName[node.resolution],button,'muted');
    button.onclick=()=>select(node.id);
  }
}
function select(id) {
  focus=id; currentView='local';
  const node=nodes.get(id), box=document.getElementById('detail'); box.replaceChildren();
  el('h3',node.title,box); el('p','点击关系查看原文依据。',box,'muted');
  if(node.issue_year_hint) el('p','原文指向 '+node.issue_year_hint+' 年印发的版本。',box);
  if(node.resolution==='ambiguous') {
    el('p','同名候选版本如下，尚未自动选定：',box);
    for(const candidateId of node.candidate_policy_ids||[]) {
      const candidate=nodes.get(candidateId);
      const button=el('button',candidate.title+' · '+(candidate.doc_number||'文号未知'),box,'relation');
      button.onclick=()=>select(candidateId);
    }
  }
  draw();
}
function showEdge(edge) {
  const box=document.getElementById('detail'); box.replaceChildren();
  el('h3',`${nodes.get(edge.source).title} → ${nodes.get(edge.target).title}`,box);
  el('span',typeName[edge.type],box,'badge'); el('span',stateName[edge.review_status]||edge.review_status,box,'badge');
  for(const citation of edge.citations) {
    el('p',`来源页码：${citation.page_start||'未知'}${citation.page_end&&citation.page_end!==citation.page_start?'—'+citation.page_end:''}`,box,'muted');
    el('div',citation.evidence_text,box,'evidence'); el('p','条款 ID：'+citation.clause_id,box,'muted');
    if(citation.effective_date) el('p','关系记录的生效日期：'+citation.effective_date,box);
    const details=el('details',undefined,box); el('summary','展开完整条款',details); el('div',citation.raw_text,details,'evidence');
  }
}
function relationList(edges,maximum=edges.length) {
  const row=document.getElementById('relations'); row.replaceChildren();
  if(edges.length>maximum) el('p',`总图列表列出前 ${maximum} 条；选择文件可查看其完整直接关系。`,row,'muted');
  for(const edge of edges.slice(0,maximum)) {
    const button=el('button',`${nodes.get(edge.source).title} → ${typeName[edge.type]} → ${nodes.get(edge.target).title}`,row,'relation');
    el('div',(stateName[edge.review_status]||edge.review_status)+' · '+edge.citations.length+' 处原文依据',button,'muted');
    button.onclick=()=>showEdge(edge);
  }
}
function drawNode(node,x,y,width,height) {
  const group=sv('g',{class:'node',tabindex:0,role:'button','aria-label':node.title},svg);
  sv('title',{},group).textContent=node.title+' '+(node.doc_number||'');
  sv('rect',{x,y,width,height,rx:2,fill:node.id===focus?'#f0f3ff':'#fff',stroke:node.policy_id?'#002fa7':'#a0a6af','stroke-dasharray':node.policy_id?'':'4 3'},group);
  const chars=width>200?16:11, text=sv('text',{x:x+width/2,y:y+height/2-5,'text-anchor':'middle'},group);
  for(let i=0;i<2;i++) sv('tspan',{x:x+width/2,dy:i?18:0},text).textContent=node.title.slice(i*chars,(i+1)*chars)+(i===1&&node.title.length>chars*2?'…':'');
  group.onclick=()=>select(node.id);
  group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(node.id);}};
}
function drawLocal() {
  const root=nodes.get(focus);
  if(!root){document.getElementById('focus-title').textContent='当前没有文件节点';return;}
  document.getElementById('focus-title').textContent=root.title;
  document.getElementById('focus-meta').textContent=[root.doc_number||'文号未明确',resolutionName[root.resolution],validityName[root.validity_status]||'效力待核实',root.effective_date?'生效日期 '+root.effective_date:''].filter(Boolean).join(' · ');
  // 局部图按关系数量延长画布，避免展示上限截断入向或出向引用。
  // 引用与提及在上，已审核废止随后，待审核废止统一放到最下方。
  const order=edge=>edge.type==='cites'?0:edge.type==='mentions'?1:edge.review_status==='pending'?3:2;
  const matches=visibleEdges().filter(edge=>edge.source===focus||edge.target===focus).sort((a,b)=>order(a)-order(b)),edges=matches;
  let sectionGap=0;
  const rows=edges.map((edge,index)=>{if(index&&order(edge)!==order(edges[index-1]))sectionGap+=36;return 60+index*84+sectionGap;});
  const height=Math.max(440,(rows.at(-1)||60)+70), mid=height/2;
  svg.setAttribute('viewBox',`0 0 900 ${height}`);
  document.getElementById('view-count').textContent=`直接关系 ${matches.length} 条，图中展示 ${edges.length} 条；完整关系见下方列表`;
  document.getElementById('graph-help').textContent='点击关联文件继续查看；点击“全库总图”返回全部文件关系。';
  // 入向曲线末段保持向右，终点在主节点左边界外，避免箭头反向进入节点而被遮住。
  for(const [index,edge] of edges.entries()) {
    const outgoing=edge.source===focus, y=rows[index];
    const from=outgoing?[540,mid]:[265,y], to=outgoing?[621,y]:[346,mid];
    const path=sv('path',{d:`M ${from[0]} ${from[1]} C ${from[0]+30} ${from[1]} ${to[0]-30} ${to[1]} ${to[0]} ${to[1]}`,fill:'none',stroke:edgeColor(edge),'stroke-width':1.6,'marker-end':edgeMarker(edge),'stroke-dasharray':dash(edge),'data-edge-id':edge.id,class:'local-edge'},svg);
    path.style.cursor='pointer'; path.onclick=()=>showEdge(edge);
    sv('text',{x:outgoing?552:276,y:y-14},svg).textContent=typeName[edge.type]+(edge.review_status==='pending'?' · 待审核':'');
  }
  // 所有连线先于节点绘制，箭头已在节点边界外，无需依靠图层遮挡修饰。
  for(const [index,edge] of edges.entries()) {
    const outgoing=edge.source===focus;
    drawNode(nodes.get(outgoing?edge.target:edge.source),outgoing?635:25,rows[index]-27,240,54);
  }
  drawNode(root,360,mid-38,180,76);
  if(!edges.length) sv('text',{x:450,y:mid+80,'text-anchor':'middle'},svg).textContent='当前筛选下没有直接关系';
  relationList(matches);
}

function overviewLayout(selectedNodes,edges,{compact=false}={}) {
  // 强连通分量只参与排布，原始文件与有向关系始终保持独立。
  const adjacency=new Map(selectedNodes.map(node=>[node.id,new Set()]));
  const outgoing=new Map(selectedNodes.map(node=>[node.id,new Set()]));
  for(const edge of edges) {
    adjacency.get(edge.source).add(edge.target);adjacency.get(edge.target).add(edge.source);
    outgoing.get(edge.source).add(edge.target);
  }
  const components=[],isolated=[],seen=new Set();
  for(const id of [...adjacency.keys()].sort()) {
    if(seen.has(id)) continue;
    const group=[id];seen.add(id);
    for(let i=0;i<group.length;i++) for(const next of adjacency.get(group[i])) if(!seen.has(next)){seen.add(next);group.push(next);}
    if(group.length===1&&!outgoing.get(id).size) isolated.push(id);else components.push(group);
  }
  components.sort((a,b)=>b.length-a.length||a[0].localeCompare(b[0]));
  const boxes=[];
  for(const group of components) {
    const members=new Set(group),localEdges=edges.filter(edge=>members.has(edge.source));
    const indices=new Map(),low=new Map(),stack=[],active=new Set(),sccs=[],sccByNode=new Map();let serial=0;
    function visit(id) {
      indices.set(id,serial);low.set(id,serial++);stack.push(id);active.add(id);
      for(const next of outgoing.get(id)) {
        if(!indices.has(next)){visit(next);low.set(id,Math.min(low.get(id),low.get(next)));}
        else if(active.has(next)) low.set(id,Math.min(low.get(id),indices.get(next)));
      }
      if(low.get(id)===indices.get(id)) {
        const scc=[];let current;
        do{current=stack.pop();active.delete(current);sccByNode.set(current,sccs.length);scc.push(current);}while(current!==id);
        sccs.push(scc.sort());
      }
    }
    for(const id of [...group].sort()) if(!indices.has(id)) visit(id);
    const nextScc=sccs.map(()=>new Set()),indegree=sccs.map(()=>0),ranks=sccs.map(()=>0);
    for(const edge of localEdges) {
      const a=sccByNode.get(edge.source),b=sccByNode.get(edge.target);
      if(a!==b&&!nextScc[a].has(b)){nextScc[a].add(b);indegree[b]++;}
    }
    const queue=indegree.flatMap((degree,index)=>degree===0?[index]:[]);
    for(let i=0;i<queue.length;i++) for(const next of nextScc[queue[i]]) {
      ranks[next]=Math.max(ranks[next],ranks[queue[i]]+1);
      if(--indegree[next]===0) queue.push(next);
    }
    const layers=Array.from({length:Math.max(...ranks)+1},()=>[]),rankById=new Map(),previous=new Map(),next=new Map(),edgeChains=new Map();
    function add(id,rank){layers[rank].push(id);rankById.set(id,rank);previous.set(id,new Set());next.set(id,new Set());}
    for(const id of [...group].sort()) add(id,ranks[sccByNode.get(id)]);
    for(const edge of localEdges) {
      const from=rankById.get(edge.source),to=rankById.get(edge.target),chain=[edge.source];
      // 临时点占用相应层内的位置，避免长边直接穿过中间层的节点。
      for(let rank=from+1;rank<to;rank++){const id=`layout:${edge.id}:${rank}`;add(id,rank);chain.push(id);}
      chain.push(edge.target);edgeChains.set(edge.id,chain);
      for(let i=1;i<chain.length;i++) if(rankById.get(chain[i])>rankById.get(chain[i-1])) {
        previous.get(chain[i]).add(chain[i-1]);next.get(chain[i-1]).add(chain[i]);
      }
    }
    const order=new Map();
    function remember(layer){layer.forEach((id,index)=>order.set(id,index));}
    layers.forEach(remember);
    // 相邻层往返重心排序，平分时保留旧顺序以保证结果稳定。
    for(let sweep=0;sweep<10;sweep++) {
      const forward=sweep%2===0,sequence=forward?[...layers.keys()]:[...layers.keys()].reverse();
      for(const rank of sequence) {
        const layer=layers[rank],scores=new Map();
        for(const id of layer) {
          const peers=[...(forward?previous:next).get(id)];
          scores.set(id,peers.length?peers.reduce((sum,peer)=>sum+order.get(peer)/Math.max(1,layers[rankById.get(peer)].length-1),0)/peers.length:order.get(id)/Math.max(1,layer.length-1));
        }
        layer.sort((a,b)=>scores.get(a)-scores.get(b)||order.get(a)-order.get(b));remember(layer);
      }
    }
    // 外部目标很多时，将过高的层换成紧凑多列；各层横向范围仍互不交叠。
    const columns=layers.map(layer=>compact&&layer.length>40?Math.ceil(layer.length/28):1);
    const rows=layers.map((layer,rank)=>Math.ceil(layer.length/columns[rank]));
    const layerX=[];let cursor=70;
    for(const count of columns){layerX.push(cursor);cursor+=(count-1)*48+180;}
    const height=Math.max(150,...rows.map(count=>count*48+80)),width=Math.max(180,cursor-110),allPoints=new Map();
    layers.forEach((layer,rank)=>layer.forEach((id,index)=>allPoints.set(id,{x:layerX[rank]+(index%columns[rank])*48,y:height/2+(Math.floor(index/columns[rank])-(rows[rank]-1)/2)*48})));
    const positions=new Map(group.map(id=>[id,allPoints.get(id)]));
    const routes=new Map(localEdges.map(edge=>[edge.id,edgeChains.get(edge.id).map(id=>allPoints.get(id))]));
    boxes.push({positions,routes,width,height,isolated:false});
  }
  if(isolated.length) {
    const columns=Math.min(24,isolated.length),positions=new Map(isolated.map((id,index)=>[id,{x:40+(index%columns)*40,y:45+Math.floor(index/columns)*40}]));
    boxes.push({positions,routes:new Map(),width:columns*40+60,height:Math.ceil(isolated.length/columns)*40+80,isolated:true});
  }
  // 先打包有关联的分量，再将无关联文件整体放在末尾。
  const area=boxes.filter(box=>!box.isolated).reduce((sum,box)=>sum+(box.width+70)*(box.height+70),0);
  const maxWidth=Math.max(1200,Math.sqrt(area*1.8),...boxes.map(box=>box.width)),positions=new Map(),routes=new Map();let x=30,y=30,rowHeight=0;
  for(const box of boxes) {
    if(x>30&&(box.isolated||x+box.width>maxWidth)){y+=rowHeight+70;x=30;rowHeight=0;}
    const offset=point=>({x:point.x+x,y:point.y+y});
    for(const [id,point] of box.positions) positions.set(id,offset(point));
    for(const [id,points] of box.routes) routes.set(id,points.map(offset));
    x+=box.width+70;rowHeight=Math.max(rowHeight,box.height);
  }
  return {positions,routes,width:maxWidth+60,height:Math.max(400,y+rowHeight+30)};
}
function overviewEdgePath(edge,layout,bend,sourceRadius=6,targetRadius=6) {
  const points=layout.routes.get(edge.id).map(point=>({...point})),a=points[0],b=points.at(-1);
  const sourcePad=sourceRadius+3,targetPad=targetRadius+6;
  if(a.x===b.x) {
    // 环内关系从侧面绕行，双向边各用一侧，自环单独绘制。
    if(edge.source===edge.target) return `M ${a.x+sourcePad*0.8} ${a.y-sourcePad*0.6} C ${a.x+62} ${a.y-65} ${a.x+62} ${a.y+65} ${a.x+targetPad*0.8} ${a.y+targetPad*0.6}`;
    const side=edge.source<edge.target?1:-1,offset=side*(55+Math.abs(bend));
    return `M ${a.x+side*sourcePad} ${a.y} C ${a.x+offset} ${a.y} ${b.x+offset} ${b.y} ${b.x+side*targetPad} ${b.y}`;
  }
  const direction=b.x>a.x?1:-1;
  a.x+=direction*sourcePad;b.x-=direction*targetPad;
  if(points.length===2&&bend) points.splice(1,0,{x:(a.x+b.x)/2,y:(a.y+b.y)/2+bend});
  else for(let i=1;i<points.length-1;i++) points[i].y+=bend;
  let path=`M ${a.x} ${a.y}`;
  for(let i=1;i<points.length;i++) {
    const from=points[i-1],to=points[i],mid=(from.x+to.x)/2;
    path+=` C ${mid} ${from.y} ${mid} ${to.y} ${to.x} ${to.y}`;
  }
  return path;
}
function applyCamera(){if(viewport) viewport.setAttribute('transform',`translate(${camera.x} ${camera.y}) scale(${camera.scale})`);}
function fitView() {
  if(currentView!=='global') return;
  const scale=Math.min(1120/worldBounds.width,620/worldBounds.height);
  camera={scale,x:(1200-worldBounds.width*scale)/2,y:(700-worldBounds.height*scale)/2}; applyCamera();
}
function zoom(factor,point={x:600,y:350}) {
  if(currentView!=='global') return;
  const next=Math.max(0.02,Math.min(30,camera.scale*factor)), ratio=next/camera.scale;
  camera={scale:next,x:point.x-(point.x-camera.x)*ratio,y:point.y-(point.y-camera.y)*ratio}; applyCamera();
}
function drawGlobal() {
  const includeExternal=document.getElementById('show-external').checked;
  const edges=visibleEdges().filter(edge=>includeExternal||(nodes.get(edge.source).policy_id&&nodes.get(edge.target).policy_id));
  const externalIds=new Set(edges.flatMap(edge=>[edge.source,edge.target]));
  const selectedNodes=data.nodes.filter(node=>node.policy_id||(includeExternal&&externalIds.has(node.id)));
  const layout=overviewLayout(selectedNodes,edges,{compact:includeExternal}); worldBounds=layout;
  svg.setAttribute('viewBox','0 0 1200 700'); viewport=sv('g',{id:'viewport'},svg);
  document.getElementById('focus-title').textContent='全库文件关系总图';
  document.getElementById('focus-meta').textContent='文件关系从左向右分层显示；层次仅用于显示关系方向，不代表制度效力或管理层级。';
  document.getElementById('view-count').textContent=`总图 ${selectedNodes.length} 个节点、${edges.length} 条关系；入库文件 ${selectedNodes.filter(node=>node.policy_id).length} 份`;
  document.getElementById('graph-help').textContent='滚轮缩放、空白处拖动，或使用上方按钮。悬停查看文件名，点击节点进入局部图。孤立节点表示当前筛选下没有显示关联。';
  const labels=new Set([...selectedNodes].sort((a,b)=>citationCount(b.id)-citationCount(a.id)||(degree.get(b.id)||0)-(degree.get(a.id)||0)).slice(0,10).map(node=>node.id));
  const parallel=new Map(),pairKey=edge=>[edge.source,edge.target].sort().join('|');
  for(const edge of edges){const key=pairKey(edge);if(!parallel.has(key))parallel.set(key,[]);parallel.get(key).push(edge.id);}
  for(const edge of edges) {
    const siblings=parallel.get(pairKey(edge)),bend=(siblings.indexOf(edge.id)-(siblings.length-1)/2)*26;
    const direct=overviewEdgePath(edge,layout,bend,overviewNodeRadius(edge.source),overviewNodeRadius(edge.target));
    const appearance=overviewEdgeStyle(edge);
    const line=sv('path',{d:direct,fill:'none',stroke:edgeColor(edge),'stroke-opacity':appearance.opacity,'stroke-width':appearance.width,'marker-end':edgeMarker(edge),'stroke-dasharray':dash(edge),class:'global-edge','data-edge-id':edge.id,'data-source':edge.source,'data-target':edge.target,'data-base-opacity':appearance.opacity,'data-base-width':appearance.width},viewport);
    sv('title',{},line).textContent=typeName[edge.type]+(edge.type==='cites'?` · 目标文件被 ${citationCount(edge.target)} 份文件引用`:'');
    line.style.cursor='pointer';line.onclick=()=>showEdge(edge);
  }
  for(const node of selectedNodes) {
    const point=layout.positions.get(node.id),radius=overviewNodeRadius(node.id);
    const group=sv('g',{class:'node global-node','data-node-id':node.id,tabindex:0,role:'button','aria-label':node.title},viewport);
    sv('title',{},group).textContent=node.title+(node.doc_number?' · '+node.doc_number:'')+` · 被 ${citationCount(node.id)} 份文件引用`+' · 点击查看局部图';
    sv('circle',{cx:point.x,cy:point.y,r:radius,fill:node.policy_id?'#002fa7':'#fff',stroke:node.policy_id?'#002fa7':'#919aa9','stroke-width':1.2},group);
    const label=sv('text',{x:point.x+radius+4,y:point.y-radius-3,class:'global-label',visibility:labels.has(node.id)?'visible':'hidden'},group);
    label.textContent=node.title.length>18?node.title.slice(0,18)+'…':node.title;
    group.onmouseenter=()=>{
      label.setAttribute('visibility','visible');
      highlightOverview(node.id);
    };
    group.onmouseleave=()=>{
      label.setAttribute('visibility',labels.has(node.id)?'visible':'hidden');
      highlightOverview();
    };
    group.onclick=()=>select(node.id);
    group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(node.id);}};
  }
  relationList(edges,200);fitView();
}
function draw() {
  svg.replaceChildren();viewport=null;svg.classList.toggle('overview',currentView==='global');
  document.getElementById('mode-global').setAttribute('aria-pressed',currentView==='global');
  document.getElementById('mode-local').setAttribute('aria-pressed',currentView==='local');
  for(const id of ['zoom-in','zoom-out','fit-view']) document.getElementById(id).disabled=currentView!=='global';
  document.getElementById('external-filter').hidden=currentView!=='global';
  addMarker();showList();if(currentView==='global') drawGlobal();else drawLocal();
}
function svgPoint(event){return new DOMPoint(event.clientX,event.clientY).matrixTransform(svg.getScreenCTM().inverse());}
svg.addEventListener('wheel',event=>{if(currentView==='global'){event.preventDefault();zoom(event.deltaY<0?1.16:1/1.16,svgPoint(event));}},{passive:false});
let dragging=null;
svg.addEventListener('pointerdown',event=>{
  if(currentView!=='global'||event.target.closest('.node')||event.target.closest('[data-edge-id]')) return;
  dragging={point:svgPoint(event),x:camera.x,y:camera.y};svg.setPointerCapture(event.pointerId);svg.classList.add('dragging');
});
svg.addEventListener('pointermove',event=>{if(dragging){const point=svgPoint(event);camera.x=dragging.x+point.x-dragging.point.x;camera.y=dragging.y+point.y-dragging.point.y;applyCamera();}});
function stopDragging(){dragging=null;svg.classList.remove('dragging');}
svg.addEventListener('pointerup',stopDragging);svg.addEventListener('pointercancel',stopDragging);
for(const [value,label] of [[data.stats?.documents??data.nodes.filter(n=>n.policy_id).length,'入库文件'],[data.edges.length,'文件关系'],[data.stats?.unresolved_targets??data.nodes.filter(n=>!n.policy_id).length,'未解析目标']]) {
  const box=el('div',undefined,document.getElementById('metrics'));el('strong',value,box);el('span',label,box,'muted');
}
document.getElementById('mode-global').onclick=()=>{currentView='global';draw();};
document.getElementById('mode-local').onclick=()=>{if(focus) select(focus);};
document.getElementById('zoom-in').onclick=()=>zoom(1.4);
document.getElementById('zoom-out').onclick=()=>zoom(1/1.4);
document.getElementById('fit-view').onclick=fitView;
document.getElementById('search').addEventListener('input',showList);
for(const id of ['show-mentions','show-pending','show-external']) document.getElementById(id).onchange=draw;
draw();
