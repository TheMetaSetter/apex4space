/* Area -> read-only API -> maps, calendar and grounded local chat. */
const $ = id => document.getElementById(id);
const number = value => new Intl.NumberFormat('en').format(value);
const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
let config, areaName = 'World', frame = 'explore', calendarEnd, completeEnd, dayGeneration = 0, viewGeneration = 0;
let answerPages = [], answerPage = 0, history = [];
const yearCache = new Map();
const pendingRequests = new Map();
let requestQueue = Promise.resolve();
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
proj4.defs('EPSG:6933', '+proj=cea +lat_ts=30 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs');
ol.proj.proj4.register(proj4);
const projection = ol.proj.get('EPSG:6933');
projection.setExtent([-17367530.45,-7324184.56,17367530.45,7324184.56]);
projection.setWorldExtent([-180,-86,180,86]);
const format = new ol.format.GeoJSON();
const read = data => format.readFeatures(data,{dataProjection:'EPSG:4326',featureProjection:projection});
const yearStyle = {'fill-color':['interpolate',['linear'],['get','active_fraction'],0,'#99502d',0.3,'#ff6a1f',1,'#f3ebdd']};
const dailyStyle = {'fill-color':'#ff6a1f','stroke-color':'#ffa575','stroke-width':0.4};
function makeMap(target, yearly = false, sharedView = null) {
  const source = new ol.source.Vector({wrapX:false});
  const outlines = new ol.source.Vector({wrapX:false});
  const cellLayer = new ol.layer.WebGLVector({source,style:yearly ? yearStyle : dailyStyle,variables:{maxDays:366}});
  const map = new ol.Map({target,layers:[
    new ol.layer.Vector({source:new ol.source.Vector({url:'world.geojson',format,wrapX:false,attributions:'Natural Earth'}),
      style:{'fill-color':'#164943','stroke-color':'#6a8b762f','stroke-width':0.5}}),
    new ol.layer.Vector({source:outlines,style:{'stroke-color':'#c0d1b9','stroke-width':1,'fill-color':'#f3ebdd05'}}),cellLayer],
    view:sharedView || new ol.View({projection,center:[-9000000,4500000],zoom:2,maxZoom:15}),
    controls:ol.control.defaults.defaults({rotate:false})});
  return {map,source,outlines,cellLayer};
}
const exploreMap = makeMap('explore-map',true);
const compareView = new ol.View({projection,center:[-9000000,4500000],zoom:2,maxZoom:15});
const mapA = makeMap('map-a',true,compareView), mapB = makeMap('map-b',true,compareView);
const mini = makeMap('mini-map');
mini.map.getInteractions().clear();
function boundaryFeature() {
  return read(config.boundaries).find(f => f.get('area_id') === config.areas.find(a => a.name === areaName)?.id);
}
function fit(item, animate = false) {
  const boundary=boundaryFeature(),area=config.areas.find(a=>a.name===areaName);
  item.outlines.clear();if(boundary)item.outlines.addFeature(boundary);item.map.updateSize();
  let extent=area?.bbox?ol.proj.transformExtent([Math.max(-180,area.bbox[0]),Math.max(-85.05,area.bbox[1]),Math.min(180,area.bbox[2]),Math.min(85.05,area.bbox[3])],'EPSG:4326',projection):boundary?.getGeometry().getExtent();
  if(!extent)extent=projection.getExtent();
  if(areaName==='North America')extent=ol.proj.transformExtent([-170,5,-20,85],'EPSG:4326',projection);
  item.map.getView().fit(extent,{padding:[25,25,25,25],duration:animate && !reduceMotion ? 400 : 0,maxZoom:7});
}
function showError(error) { $('error').textContent = error.message || String(error); $('error').hidden = false; }
function post(path, payload) {
  const key=path+JSON.stringify(payload);
  if(pendingRequests.has(key))return pendingRequests.get(key);
  const result=requestQueue.catch(()=>{}).then(()=>sendRequest(path,payload));
  requestQueue=result;pendingRequests.set(key,result);
  result.finally(()=>pendingRequests.delete(key)).catch(()=>{});
  return result;
}
async function sendRequest(path, payload) {
  $('status').textContent = config?.cloud?'Reading cloud data…':'Reading local data…';
  const response = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload),signal:AbortSignal.timeout(path.includes('chat') ? 200000 : 65000)});
  const data = await response.json();
  if (!response.ok){$('status').textContent='Selection unavailable';throw new Error(data.message || data.error?.message || data.detail?.[0]?.msg || 'Could not load this selection.');}
  $('status').textContent = `${config?.cloud?'Cloud':'Local'} release · coverage unknown`;
  return data;
}
function rangeFeatures(data,scale){return read({...data,features:data.features.map(f=>({...f,properties:{...f.properties,active_fraction:f.properties.active_days/Math.max(1,scale)}}))});}
function viewBounds(item) {
  const bounds=projection.getExtent();
  const raw=item.map.getView().calculateExtent(item.map.getSize());
  const clipped=[Math.max(bounds[0],raw[0]),Math.max(bounds[1],raw[1]),Math.min(bounds[2],raw[2]),Math.min(bounds[3],raw[3])];
  const extent=ol.proj.transformExtent(clipped.every(Number.isFinite)?clipped:bounds,projection,'EPSG:4326');
  return [Math.max(-180,Math.min(180,extent[0])),Math.max(-86,Math.min(86,extent[1])),Math.max(-180,Math.min(180,extent[2])),Math.max(-86,Math.min(86,extent[3]))];
}
async function rangeData(start,end,item,selectedArea=areaName,valid=()=>true) {
  let offset=0,result,features=[];
  const bbox=item?viewBounds(item):undefined;
  const details=!!item&&item.map.getTargetElement().getBoundingClientRect().width>0&&item.map.getView().getZoom()>=2.5;
  if(item)item.map.getTargetElement().dataset.detail=details?'':'Overview · zoom in to load 10 km cells';
  do {
    const page=await post('/v2/hotspots/ranges/query',{release_id:config.release_id,area_name:selectedArea,start_date:start,end_date:end,offset,page_size:config.page_size||1000,bbox,include_geometry:details});
    if(!valid()) return null;
    result=page;features.push(...page.features);offset=page.next_offset;
  } while(offset!==null);
  return {...result,features};
}
async function loadDay() {
  const generation=++dayGeneration; $('error').hidden=true;
  if($('day').value>$('day-end').value){showError(new Error('From must be on or before To.'));return;}
  $('daily-count').textContent='—';$('daily-state').textContent='Loading selected range…';exploreMap.source.clear();
  try {
    const data=await rangeData($('day').value,$('day-end').value,exploreMap,areaName,()=>generation===dayGeneration);
    if(!data)return;
    exploreMap.source.addFeatures(rangeFeatures(data,data.selected_days));
    $('daily-count').textContent=number(data.unique_active_cells);
    $('daily-state').textContent=`${data.selected_days} ${data.selected_days===1?'day':'days'} · ${number(data.total_cell_days)} cell-days. Map: ${exploreMap.map.getView().getZoom()<2.5?'zoom in for cells':`${number(data.features.length)} cells loaded in view`}. Coverage unknown.`;
  }catch(error){if(generation===dayGeneration){showError(error);$('daily-state').textContent='Selection unavailable. Please try again.';}}
}
async function yearData(year, selectedArea = areaName) {
  const key = `${selectedArea}:${year}`;
  if (!yearCache.has(key)) {
    const promise=post('/v2/hotspots/years/query',{release_id:config.release_id,area_name:selectedArea,year,page_size:1});
    if(yearCache.size>=6) yearCache.delete(yearCache.keys().next().value);
    yearCache.set(key,promise);
    promise.catch(() => yearCache.delete(key));
  }
  return yearCache.get(key);
}
function statBlock(data) {
  const section = document.createElement('section'); section.className='stat-year';
  const title = document.createElement('h3'); title.textContent=`${data.start_date} → ${data.end_date}`; section.append(title);
  const badge = document.createElement('span'); badge.className='badge'; badge.textContent=`${data.selected_days} selected days · coverage unknown`; section.append(badge);
  for(const [label,value] of [['Unique active cells',number(data.unique_active_cells)],['Total cell-days',number(data.total_cell_days)],['Peak activity date',data.peak_date || 'No records'],['Peak daily cells',number(data.peak_count)],['Average daily cells',number(data.average_daily_active_cells)]]) {
    const p = document.createElement('p'), strong=document.createElement('strong'); p.textContent=label; strong.textContent=value; p.append(strong); section.append(p);
  }
  if(data.polar_cells) { const p=document.createElement('p');p.textContent=`${data.polar_cells} polar cells counted but outside this map.`;section.append(p); }
  return section;
}
async function loadCompare() {
  const generation=++viewGeneration,selectedArea=areaName;
  $('stats-content').textContent='Loading both ranges…';$('error').hidden=true;mapA.source.clear();mapB.source.clear();
  try {
    const valid=()=>generation===viewGeneration;
    const a=await rangeData($('start-a').value,$('end-a').value,mapA,selectedArea,valid);
    if(!a)return;
    const b=await rangeData($('start-b').value,$('end-b').value,mapB,selectedArea,valid);
    if(!b)return;
    const maxDays=Math.max(1,a.selected_days,b.selected_days);
    for(const [item,data] of [[mapA,a],[mapB,b]]){item.source.clear();item.source.addFeatures(rangeFeatures(data,maxDays));}
    $('compare-area-a').textContent=`${selectedArea} · Range A`;$('compare-area-b').textContent=`${selectedArea} · Range B`;
    $('stats-content').replaceChildren(statBlock(a),statBlock(b));
    const note=document.createElement('p');note.className='small';note.textContent=`Shared 1–${maxDays} active-day map scale. Maps show loaded cells in view; totals cover the selected area. Longer ranges may have larger totals. Averages divide by selected days, not observation coverage. Overlapping dates remain in each range.`;$('stats-content').append(note);
  }catch(error){if(generation===viewGeneration){showError(error);$('stats-content').textContent='Range data unavailable.';}}
}
function heat(value, maximum) {
  if(value === null) return '';
  if(value === 0) return '#254c46';
  const ratio=Math.sqrt(value/Math.max(1,maximum));
  const low=ratio<0.5?[114,63,35]:[255,106,31], high=ratio<0.5?[255,106,31]:[243,235,221];
  const amount=ratio<0.5?ratio*2:(ratio-0.5)*2;
  return `rgb(${low.map((v,i)=>Math.round(v+(high[i]-v)*amount)).join(',')})`;
}
function makeCalendarYear(data,maximum) {
  const row=document.createElement('div');row.className='calendar-year';
  const title=document.createElement('h3');title.textContent=`${data.year}${data.complete_year?'':' *'}`;row.append(title);
  const grid=document.createElement('div');grid.className='months';row.append(grid);
  for(let month=0;month<12;month++) {
    const block=document.createElement('div'), label=document.createElement('p'), days=document.createElement('div');
    label.className='month-name';label.textContent=months[month];days.className='month-days';block.append(label,days);grid.append(block);
    const first=new Date(Date.UTC(data.year,month,1)).getUTCDay();
    for(let i=0;i<first;i++) days.append(document.createElement('span'));
    for(const day of data.days.filter(d=>Number(d.date.slice(5,7))===month+1)) {
      const button=document.createElement('button');button.className='calendar-day';button.type='button';
      const description=`${day.date}: ${day.active_cell_count === null ? 'outside release dates' : `${number(day.active_cell_count)} active cells; coverage unknown`}`;
      button.setAttribute('aria-label',description);button.title=description;
      if(day.active_cell_count === null) { button.classList.add('missing');button.disabled=true; }
      else { button.style.background=heat(day.active_cell_count,maximum);button.onclick=()=>{$('day').value=day.date;$('day-end').value=day.date;switchFrame('explore');loadDay();}; }
      button.onfocus=button.onmouseenter=()=>{$('calendar-detail').textContent=description;};days.append(button);
    }
  }
  return row;
}
function card(label,value,note) {
  const item=document.createElement('div');item.className='card';
  for(const [tag,text] of [['span',label],['strong',value],['small',note]]) { const child=document.createElement(tag);child.textContent=text;item.append(child); }
  return item;
}
async function loadCalendar() {
  const generation=++viewGeneration, selectedArea=areaName;
  const first=Math.max(Number(config.start_date.slice(0,4)),calendarEnd-2);
  $('year-range').textContent=`${first}—${calendarEnd}`;$('calendar-area').textContent=selectedArea;
  $('earlier').disabled=first<=Number(config.start_date.slice(0,4));$('later').disabled=calendarEnd>=Number(config.end_date.slice(0,4));
  $('calendar-rows').textContent='Reading daily activity…';
  try {
    const years=[];
    for(let year=first;year<=calendarEnd;year++) years.push(await yearData(year,selectedArea));
    if(generation !== viewGeneration) return;
    const maximum=Math.max(1,...years.map(y=>y.peak_count));
    $('calendar-rows').replaceChildren(...years.map(y=>makeCalendarYear(y,maximum)));
    const latest=years.at(-1),peakMonth=latest.monthly_cell_days.indexOf(Math.max(...latest.monthly_cell_days));
    $('calendar-cards').replaceChildren(card('Active cell-days',number(latest.total_cell_days),`${latest.year} · one cell, one UTC day`),
      card('Peak month',latest.total_cell_days ? months[peakMonth] : 'No records',`${latest.year} · ${number(latest.monthly_cell_days[peakMonth])} cell-days`),
      card('Peak day',latest.peak_date || 'No records',`${number(latest.peak_count)} active cells · coverage unknown`));
    $('calendar-detail').textContent='Select a day to explore. * Partial year. Colors share one scale across these years.';fit(mini);
  } catch(error) { showError(error);$('calendar-rows').textContent='Calendar data unavailable.'; }
}
function switchFrame(name) {
  if(!config)return;
  frame=name;$('error').hidden=true;
  document.querySelectorAll('.frame').forEach(el=>el.classList.toggle('active',el.id===name));
  document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.frame===name)));
  requestAnimationFrame(()=>{[exploreMap,mapA,mapB,mini].forEach(item=>item.map.updateSize());
    if(name==='compare'){fitOnce(mapA);fitOnce(mapB);loadCompare();}if(name==='calendar') loadCalendar();});
}
function renderAnswer() {
  $('answer').textContent=answerPages[answerPage] || '';$('answer-page').textContent=`${answerPage+1} / ${Math.max(1,answerPages.length)}`;
  $('answer-back').disabled=answerPage===0;$('answer-next').disabled=answerPage>=answerPages.length-1;
}
function setAnswer(text) {
  answerPages=[];let page='';
  const lines=text.split('\n').flatMap(line=>line.match(/.{1,260}(?:\s|$)|.{1,260}/g)||['']);
  for(const line of lines){
    if(page&&page.length+line.length+1>260){answerPages.push(page);page='';}
    page+=(page?'\n':'')+line;
  }
  if(page)answerPages.push(page);
  answerPage=0;renderAnswer();
}

function chatRanges(){
  if(frame==='compare')return ['a','b'].map(side=>({start_date:$(`start-${side}`).value,end_date:$(`end-${side}`).value}));
  if(frame==='calendar')return [{start_date:`${calendarEnd}-01-01`<config.start_date?config.start_date:`${calendarEnd}-01-01`,end_date:`${calendarEnd}-12-31`>config.end_date?config.end_date:`${calendarEnd}-12-31`}];
  return [{start_date:$('day').value,end_date:$('day-end').value}];
}
async function ask(question,compareSelected=false) {
  if(!config)return;
  $('chat').hidden=false;$('open-chat').setAttribute('aria-expanded','true');$('send').disabled=true;setAnswer(config?.cloud?'Reading your selected data…':'Thinking with your local model…');
  try {
    const data=await post('/v2/chat/query',{question,compare_selected:compareSelected&&frame==='compare',area_name:areaName,years:[$('start-a').value,$('start-b').value].map(d=>Number(d.slice(0,4))),ranges:chatRanges(),date:$('day').value,history:history.slice(-6)});
    let text=data.answer;
    for(const [i,stats] of data.data.entries()) {
      const source=data.sources[i], label=data.data.length===2?`${i===0?'A':'B'} · `:'';
      const period=source.start_date===`${source.year}-01-01`?source.year:source.start_date || source.year || stats.date;
      const dates=source.end_date?`${period} → ${source.end_date}`:period;
      const value=stats.total_cell_days ?? stats.active_cell_count;
      if(value!==undefined)text+=`\n${label}${dates}: ${value===null?'Outside release':number(value)} ${stats.total_cell_days!==undefined?'cell-days':'active cells'}`;
    }
    if(data.sources.length){const source=data.sources[0];text+=`\nSource: ${source.area_name} · release ${source.release_id.slice(0,8)} · coverage unknown`;}
    history.push(question,data.answer);setAnswer(text);$('question').value='';
  } catch(error) { setAnswer(error.message); } finally { $('send').disabled=false; }
}
$('search').onsubmit=event=>{event.preventDefault();const value=$('area').value.trim().toLowerCase();
  const found=config.areas.find(a=>a.name.toLowerCase()===value || a.aliases.includes(value));
  if(!found) {showError(new Error('Choose a listed country, continent or World.'));return;}
  areaName=found.name;$('area').value=areaName;fitOnce(exploreMap);loadDay();};
$('fit').onclick=()=>fit(exploreMap,true);
$('open-chat').onclick=()=>{$('chat').hidden=false;$('open-chat').setAttribute('aria-expanded','true');$('question').focus();};
$('header-chat').onclick=()=>$('open-chat').click();
$('close-chat').onclick=()=>{$('chat').hidden=true;$('open-chat').setAttribute('aria-expanded','false');$('open-chat').focus();};
$('chat-form').onsubmit=event=>{event.preventDefault();ask($('question').value);};
document.querySelectorAll('.starters button').forEach(b=>b.onclick=()=>ask(b.textContent,b.id==='compare-question'));
$('answer-back').onclick=()=>{answerPage--;renderAnswer();};$('answer-next').onclick=()=>{answerPage++;renderAnswer();};
document.querySelectorAll('[data-frame]').forEach(b=>b.onclick=()=>switchFrame(b.dataset.frame));
$('open-compare').onclick=()=>switchFrame('compare');
document.querySelectorAll('[data-toggle]').forEach(b=>b.onclick=()=>{const panel=$(b.dataset.toggle);panel.hidden=!panel.hidden;
  document.querySelectorAll(`[data-toggle="${b.dataset.toggle}"]`).forEach(button=>button.setAttribute('aria-expanded',String(!panel.hidden)));
  requestAnimationFrame(()=>[exploreMap,mapA,mapB,mini].forEach(item=>item.map.updateSize()));});
for(const side of ['a','b']){
  $(`year-${side}`).onchange=()=>{selectYear(side);loadCompare();};
  for(const field of ['start','end'])$(`${field}-${side}`).onchange=()=>{$(`year-${side}`).value='';loadCompare();};
}
$('one-day').onclick=()=>{$('day-end').value=$('day').value;loadDay();};
$('earlier').onclick=()=>{calendarEnd=Math.max(Number(config.start_date.slice(0,4)),calendarEnd-3);loadCalendar();};
$('later').onclick=()=>{calendarEnd=Math.min(Number(config.end_date.slice(0,4)),calendarEnd+3);loadCalendar();};
document.querySelectorAll('[data-side]').forEach(b=>b.onclick=()=>{['a','b'].forEach(s=>$(`side-${s}`).classList.toggle('selected',s===b.dataset.side));requestAnimationFrame(()=>{[mapA,mapB].forEach(item=>item.map.updateSize());if(frame==='compare')loadCompare();});});
$('side-a').classList.add('selected');
$('about-open').onclick=()=>$('about').showModal();$('about-close').onclick=()=>$('about').close();
exploreMap.map.on('singleclick',event=>{const feature=exploreMap.map.forEachFeatureAtPixel(event.pixel,item=>item.get('cell_id')?item:undefined);
  $('cell-tip').hidden=!feature;if(feature)$('cell-tip').textContent=`10 km cell ${feature.get('cell_id')} · ${$('day').value}`;});
function selectYear(side){const year=$(`year-${side}`).value;if(!year)return;$(`start-${side}`).value=`${year}-01-01`<config.start_date?config.start_date:`${year}-01-01`;$(`end-${side}`).value=`${year}-12-31`>config.end_date?config.end_date:`${year}-12-31`;}
function fitOnce(item){if(item.fittedArea!==areaName){item.fittedArea=areaName;fit(item);}}
let moveTimer;
for(const item of [exploreMap,mapA])item.map.on('moveend',()=>{if(!config)return;clearTimeout(moveTimer);moveTimer=setTimeout(()=>{if(frame==='explore')loadDay();else if(frame==='compare')loadCompare();},450);});
async function start() {
  try {
    const response=await fetch('/app/config');if(!response.ok)throw new Error('The data release is unavailable.');config=await response.json();
    if(config.cloud){document.querySelector('.local').firstChild.textContent='CLOUD DATA ';document.querySelector('#chat .eyebrow').textContent='ASK FRISM · DATA SUMMARY';}
    areaName=config.areas.some(a=>a.name==='World')?'World':config.areas[0].name;
    if(!config.areas.some(a=>a.name==='World')&&config.areas.some(a=>a.name==='North America'))areaName='North America';
    $('area').value=areaName;
    if(config.grid.equal_area===false){
      $('cell-unit').textContent='active 10 km projected cells';
      $('grid-label').textContent='EPSG:3857 source grid · UTC';
      $('grid-note').textContent='These cells are 10,000 metres wide in EPSG:3857. Their ground size varies with latitude. They are not equal-area, wildfire counts, or burned area. Zoom does not add finer source detail.';
      $('selection-note').textContent='Country membership was assigned to detections before forming cells. Continent and World totals use the union of member-country cells for each day. Shared border cells count once. The map transforms cell shapes to EPSG:6933; it does not rebuild the grid. Unmatched country points and source latitudes outside ±85.0511° were discarded by the producer.';
    }
    for(const area of config.areas){const option=document.createElement('option');option.value=area.name;$('areas').append(option);}
    for(const id of ['day','day-end','start-a','end-a','start-b','end-b']){$(id).min=config.start_date;$(id).max=config.end_date;}
    $('day').value=$('day-end').value=config.end_date;
    const startYear=Number(config.start_date.slice(0,4)),endYear=Number(config.end_date.slice(0,4));
    completeEnd=config.end_date.endsWith('12-31')?endYear:endYear-1;calendarEnd=Math.max(startYear,completeEnd);
    for(const id of ['year-a','year-b']){const option=document.createElement('option');option.value='';option.textContent='Year shortcut';$(id).append(option);}
    for(const id of ['year-a','year-b'])for(let year=endYear;year>=startYear;year--){const option=document.createElement('option');option.value=year;option.textContent=year;$(id).append(option);}
    $('year-a').value=Math.max(startYear,completeEnd-1);$('year-b').value=Math.max(startYear,completeEnd);selectYear('a');selectYear('b');
    $('release-note').textContent=`Release ${config.release_id}. Available: ${config.start_date} to ${config.end_date}.`;
    setAnswer('Ask about the selected area and date ranges. Data answers include their database source.');fitOnce(exploreMap);await loadDay();
  } catch(error){showError(error);$('status').textContent='Connection failed';}
}
start();
