/* Portable report interactions. All evidence comes from the embedded ReportModel.
   No network, instrument calls, Python callbacks, eval, or mutable issued findings. */
(() => {
  'use strict';
  const payload = JSON.parse(document.getElementById('dcdc-report-data').textContent);
  const model = payload.model;
  const specs = model.figures;
  const points = new Map(model.points.map(p => [p.point_id, p]));
  const graphs = new Map();
  const conditions = new Map();
  const clone = value => JSON.parse(JSON.stringify(value));
  const safe = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  const keyOf = series => String(series.selection_key ?? series.vin_target_V ?? series.id);
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const number = value => finite(value) ? Number(value.toPrecision(6)).toString() : 'not available';
  const identity = model.dut.identity?.model ?? model.dut.model ?? model.dut.model_text ?? model.dut.name ?? 'DUT';
  specs.forEach(spec => spec.series.forEach(series => {
    const key = keyOf(series);
    if (!conditions.has(key)) {
      const style = payload.condition_styles?.[key] ?? {};
      conditions.set(key, {label: series.label,
        color: style.color ?? payload.condition_colors?.[key] ?? payload.colors[conditions.size % payload.colors.length],
        dash: style.dash ?? 'solid', symbol: style.symbol ?? 'circle'});
    }
  }));
  const defaults = {schema_version: '1.0', run_id: model.run_id, analysis_id: model.analysis_id,
    report_revision: model.report_revision, selected_series: [...conditions.keys()], metric: 'all',
    x_key: 'default', log_current: false, hovermode: 'closest', ranges: {}};
  let state = clone(defaults);
  let updating = false;
  let pending = Promise.resolve();
  const errorBox = document.getElementById('report-error');
  const fail = error => { errorBox.textContent = 'Report interaction failed: ' + String(error.message ?? error); console.error(error); };
  const quantityLabels = {Iout_A: 'Measured output current (A)', Pout_W: 'Measured output power (W)',
    Vin_V: 'Measured input voltage (V)', elapsed_s: 'Time since first accepted query (s)'};
  function xKey(spec) { return state.x_key === 'default' ? spec.x_key : state.x_key; }
  function isLog(spec) { return state.log_current && /current|Iout_A|Iin_A/.test(xKey(spec)); }
  function plottedValue(spec, point) {
    return point.qualification === 'valid' && finite(point[xKey(spec)]) && finite(point[spec.y_key]) &&
      (!isLog(spec) || point[xKey(spec)] > 0);
  }
  function conditionRows(spec, selected = true) {
    const ids = new Set();
    for (const series of spec.series) {
      if (selected && !state.selected_series.includes(keyOf(series))) continue;
      for (const pid of series.point_ids) ids.add(pid);
    }
    return [...ids].map(id => points.get(id));
  }
  const hoverLabels = {Vin_V:'Input voltage',Iin_A:'Input current',Vout_V:'Output voltage',
    Iout_A:'Output current',Pin_W:'Input power',Pout_W:'Output power',loss_W:'Path loss',
    efficiency_pct:'Path efficiency',vout_error_pct:'Output deviation',elapsed_s:'Elapsed time'};
  function hoverValue(key, value) {
    if (!finite(value)) return 'Not available';
    if (key.endsWith('_A')) return Math.abs(value) < 1 ? (value * 1000).toFixed(1) + ' mA' : value.toFixed(3) + ' A';
    if (key.endsWith('_V')) return value.toFixed(4) + ' V';
    if (key.endsWith('_W')) return value.toFixed(3) + ' W';
    if (key.endsWith('_pct')) return value.toFixed(2) + '%';
    if (key === 'elapsed_s') return value.toFixed(1) + ' s';
    return number(value);
  }
  function hoverText(spec, point) {
    // Hover answers what is under the pointer. The point inspector retains
    // all other measurements, qualification, time bounds and raw evidence.
    const phase = point.phase_label ?? (model.evidence_label === 'MEASURED' ? 'Measured' : 'Simulated');
    const context = point.input_condition_label ?? ([...String(phase)].slice(0, 32).join('') +
      ([...String(phase)].length > 32 ? '…' : '') + ' · ' + number(point.vin_target_V) + ' V');
    const horizontal = xKey(spec);
    const lines = ['<b>' + safe(context) + '</b>',
      safe(hoverLabels[horizontal] ?? spec.x_label) + ': ' + safe(hoverValue(horizontal, point[horizontal])),
      safe(hoverLabels[spec.y_key] ?? spec.y_label) + ': <b>' + safe(hoverValue(spec.y_key, point[spec.y_key])) + '</b>'];
    // The ± text exists only where the analysis evaluated a readback budget (UNC-02).
    const band = point[spec.y_key + '_uncertainty_label'];
    if (typeof band === 'string' && spec.lower_key && spec.upper_key) lines.push('Expanded uncertainty: ' + safe(band));
    return lines.join('<br>');
  }
  function stageTransitions(spec) {
    if (spec.id !== 'fig-demand-time' || xKey(spec) !== 'elapsed_s' || spec.y_key !== 'Iout_A') return [];
    const visible = new Set(spec.series.filter(series => state.selected_series.includes(keyOf(series)))
      .flatMap(series => series.point_ids));
    let sequence = model.points;
    const executed = model.execution?.executed_point_ids;
    if (Array.isArray(executed) && executed.every(id => typeof id==='string' && points.has(id)) &&
      new Set(executed).size===executed.length && model.points.every(point =>
        !['valid','inconclusive'].includes(point.qualification) || executed.includes(point.point_id))) {
      sequence = executed.map(id => points.get(id));
    }
    // Only a recorded execution order can omit uncommanded conditional
    // candidates. Display filters cannot skip invalid or hidden windows.
    const timed = sequence.filter(point => finite(point.elapsed_s)).sort((a,b) => a.elapsed_s-b.elapsed_s);
    const nextInTime = new Map(timed.slice(1).map((point,index) => [timed[index].point_id,point.point_id]));
    const joins = [];
    for (let index=1;index<sequence.length;index++) {
      const before=sequence[index-1],after=sequence[index];
      if (![before,after].every(point => visible.has(point.point_id) && point.qualification==='valid' &&
        finite(point.elapsed_s) && finite(point.Iout_A) && finite(point.vin_target_V) && point.phase_label)) continue;
      if (before.phase_label===after.phase_label || before.vin_target_V!==after.vin_target_V ||
        before.elapsed_s>=after.elapsed_s || nextInTime.get(before.point_id)!==after.point_id) continue;
      joins.push({x:[before.elapsed_s,after.elapsed_s],y:[before.Iout_A,after.Iout_A],type:'scatter',mode:'lines',
        line:{color:'#91a1ad',width:1.5,dash:'dot'},showlegend:false,hoverinfo:'skip',connectgaps:false,
        meta:{isTransition:true}});
    }
    return joins;
  }
  function traces(spec) {
    // Guides render behind the original markers; they never enter point exports.
    const result = stageTransitions(spec);
    for (const series of spec.series) {
      const key = keyOf(series), {color, dash, symbol} = conditions.get(key);
      const rows = series.point_ids.map(id => points.get(id));
      const valid = p => plottedValue(spec, p);
      // Evidence/selection controls still retain every requested series.
      // Legends describe only curves with qualified, finite plotted values.
      if (!rows.some(valid)) continue;
      const base = {x: rows.map(p => valid(p) ? p[xKey(spec)] : null), legendgroup: key,
        visible: state.selected_series.includes(key) ? true : 'legendonly', connectgaps: false,
        meta: {conditionKey: key, seriesId: series.id}, type: 'scatter'};
      if (spec.lower_key && spec.upper_key) {
        const rgb = [1,3,5].map(i => parseInt(color.slice(i,i+2),16));
        for (const [field,fill] of [[spec.lower_key,null],[spec.upper_key,'tonexty']]) {
          result.push({...base, y: rows.map(p => valid(p) ? p[field] ?? null : null), mode:'lines',
            line:{width:0}, fill, fillcolor:'rgba('+rgb.join(',')+',0.13)',showlegend:false,hoverinfo:'skip',
            meta:{...base.meta,isBand:true}});
        }
      }
      result.push({...base, y:rows.map(p => valid(p) ? p[spec.y_key] ?? null : null), name:safe(series.label),
        mode:series.connect_points === false ? 'markers' : 'lines+markers',
        line:{color,width:2.5,dash},marker:{color,size:7,symbol},
        text:rows.map(p => hoverText(spec, p)),customdata:rows.map(p => p.point_id),
        hovertemplate:'%{text}<extra></extra>'});
    }
    return result;
  }
  function layout(spec) {
    const ranges = state.ranges[spec.id] ?? {};
    const reference = payload.figure_references?.[spec.id];
    const plottedCurrent = [...new Set(conditionRows(spec).filter(p => p.qualification === 'valid' &&
      finite(p[xKey(spec)]) && finite(p[spec.y_key])).map(p => p[xKey(spec)]))];
    const singleCurrentRange = !isLog(spec) && xKey(spec) === 'Iout_A' &&
      plottedCurrent.length === 1 && plottedCurrent[0] > 0 ? [0, 2 * plottedCurrent[0]] : undefined;
    const axisRange = ranges.x ? (isLog(spec) ? ranges.x.map(Math.log10) : ranges.x) : singleCurrentRange;
    return {template:'plotly_white', autosize:true,height:465,
      font:{family:'system-ui, sans-serif',size:12,color:'#183047'},
      // Reserve room for the three stage labels when they wrap on phones.
      // Anchoring the legend's bottom keeps it above the plotted observations.
      margin:{l:68,r:24,t:100,b:60},paper_bgcolor:'#ffffff',plot_bgcolor:'#ffffff',
      hovermode:state.hovermode,
      hoverlabel:{bgcolor:'#ffffff',bordercolor:'#bbcbd7',font:{family:'system-ui, sans-serif',size:12,color:'#183047'},align:'left'},
      legend:{orientation:'h',x:0,y:1.03,yanchor:'bottom',font:{size:11}},
      shapes:reference?[{type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:reference.value,y1:reference.value,
        line:{color:'#6b7280',width:1.2,dash:'dash'},layer:'below'}]:[],
      annotations:reference?[{xref:'paper',x:1,yref:'y',y:reference.value,text:safe(reference.label),
        xanchor:'right',yanchor:'bottom',showarrow:false,font:{size:11,color:'#59636e'},bgcolor:'rgba(255,255,255,0.85)'}]:[],
      xaxis:{title:{text:safe(quantityLabels[state.x_key] ?? spec.x_label)}, type:isLog(spec)?'log':'linear',
        gridcolor:'#e6edf1',zeroline:false,range:axisRange,autorange:!axisRange,tickformat:'~g',nticks:7},
      yaxis:{title:{text:safe(spec.y_label)},gridcolor:'#e6edf1',zeroline:false,
        range:ranges.y??reference?.y_range,autorange:!(ranges.y??reference?.y_range),tickformat:'~g',nticks:6},
      uirevision:JSON.stringify([state.selected_series,state.x_key,state.log_current,ranges])};
  }
  function syncControls() {
    document.getElementById('metric-select').value = state.metric;
    document.getElementById('x-select').value = state.x_key;
    document.getElementById('hover-select').value = state.hovermode;
    document.getElementById('log-current').checked = state.log_current;
    document.querySelectorAll('#trace-options input').forEach(input => { input.checked = state.selected_series.includes(input.dataset.series); });
    for (const spec of specs) {
      const section = document.getElementById('view-' + spec.id);
      if (section) section.hidden = state.metric !== 'all' && state.metric !== spec.id;
    }
  }
  function draw() {
    const work = async () => {
      updating = true;
      try {
        syncControls();
        for (const spec of specs) {
          const graph = graphs.get(spec.id);
          const figureLayout = layout(spec);
          // Plotly's SVG children are absolutely positioned. Reserve the same
          // height in document flow so captions cannot slide under the chart.
          graph.style.height = figureLayout.height + 'px';
          await Plotly.react(graph, traces(spec), figureLayout, {responsive:true,displaylogo:false,
            scrollZoom:false,modeBarButtonsToRemove:['toImage','sendDataToCloud'],doubleClick:'reset'});
          const rows = conditionRows(spec);
          const omitted = rows.filter(p => finite(p[xKey(spec)]) && p[xKey(spec)] <= 0).length;
          document.getElementById('status-'+spec.id).textContent =
            (isLog(spec) ? omitted + ' nonpositive-current point(s) omitted from this log view. ' : '') +
            rows.length + ' point result(s) in selected test curves. Raw observations remain unchanged.';
          if (!document.getElementById('view-'+spec.id)?.hidden) Plotly.Plots.resize(graph);
        }
      } finally { updating = false; }
    };
    pending = pending.then(work);
    return pending;
  }
  function setView(patch) {
    if (patch.run_id && patch.run_id !== model.run_id || patch.analysis_id && patch.analysis_id !== model.analysis_id) {
      return Promise.reject(new Error('View belongs to a different run or analysis'));
    }
    const allowed = new Set(['selected_series','metric','x_key','log_current','hovermode','ranges']);
    const update = {};
    for (const [key,value] of Object.entries(patch)) if (allowed.has(key)) update[key] = clone(value);
    if (update.selected_series) update.selected_series = update.selected_series.filter(key => conditions.has(String(key))).map(String);
    if (update.metric && update.metric !== 'all' && !specs.some(spec => spec.id === update.metric)) return Promise.reject(new Error('Unknown figure'));
    const horizontalKeys = ['default','Iout_A','Pout_W','Vin_V',
      ...(specs.some(spec => spec.x_key === 'elapsed_s') ? ['elapsed_s'] : [])];
    if (update.x_key && !horizontalKeys.includes(update.x_key)) return Promise.reject(new Error('Unknown horizontal quantity'));
    if (update.hovermode && !['closest','x unified'].includes(update.hovermode)) return Promise.reject(new Error('Unknown hover mode'));
    if (update.ranges) {
      for (const [fid,range] of Object.entries(update.ranges)) {
        if (!specs.some(spec => spec.id === fid)) return Promise.reject(new Error('Unknown range figure'));
        for (const dim of ['x','y']) if (range[dim] && (range[dim].length !== 2 || !range[dim].every(finite) || range[dim][0] >= range[dim][1])) {
          return Promise.reject(new Error('Axis bounds must be finite and increasing'));
        }
      }
    }
    state = {...state,...update};
    if ('x_key' in update && !('ranges' in update)) state.ranges = {};
    if (state.log_current) {
      for (const spec of specs) {
        const range = state.ranges[spec.id];
        // Ranges are stored in physical units. Positive zoom bounds survive a
        // log toggle; nonpositive bounds cannot be represented on a log axis.
        if (isLog(spec) && range?.x && range.x.some(value => value <= 0)) delete range.x;
      }
    }
    return draw();
  }
  function resetZoom() { return setView({ranges:{}}); }
  function restoreDefaults() { state = clone(defaults); return draw(); }
  function bounds(spec) {
    const graph = graphs.get(spec.id), saved = state.ranges[spec.id] ?? {};
    let x = saved.x ?? graph?._fullLayout?.xaxis?.range;
    if (x && !saved.x && isLog(spec)) x = x.map(value => Math.pow(10,value));
    const y = saved.y ?? graph?._fullLayout?.yaxis?.range;
    return {x:x ? [...x] : null,y:y ? [...y] : null};
  }
  function getSelectedPoints(scope='selected',figureId=specs[0]?.id) {
    const spec = specs.find(spec => spec.id === figureId);
    if (!spec) throw new Error('Unknown figure');
    if (!['selected','visible'].includes(scope)) throw new Error('Unknown export scope');
    const rows = conditionRows(spec);
    if (scope === 'selected') return clone(rows);
    const range = bounds(spec);
    return clone(rows.filter(p => p.qualification === 'valid' && finite(p[xKey(spec)]) && finite(p[spec.y_key]) &&
      (!isLog(spec) || p[xKey(spec)] > 0) && (!range.x || p[xKey(spec)] >= range.x[0] && p[xKey(spec)] <= range.x[1]) &&
      (!range.y || p[spec.y_key] >= range.y[0] && p[spec.y_key] <= range.y[1])));
  }
  const csvFields = ['run_id','analysis_id','evidence_type','point_id','test_id','vin_target_V',
    'programmed_input_V','input_condition_label','iout_target_A',
    'Vin_V','Iin_A','Vout_V','Iout_A','Pin_W','Pout_W','loss_W','efficiency_pct','vout_error_pct','qualification','reason',
    ...(specs.some(spec => spec.x_key === 'elapsed_s') ? ['phase_label','elapsed_start_s','elapsed_s','elapsed_end_s'] : [])];
  function csvCell(value) {
    if (value === null || value === undefined) return '';
    let text = String(value);
    if (typeof value === 'string' && (/^[\s]*[=+\-@]/.test(value) || /^[\t\r\n]/.test(value))) text = "'" + text;
    return /[",\r\n]/.test(text) ? '"' + text.replaceAll('"','""') + '"' : text;
  }
  function exportCSV(scope='selected',figureId=specs[0]?.id) {
    const spec = specs.find(spec => spec.id === figureId);
    const rows = getSelectedPoints(scope,figureId);
    const csv = [csvFields.join(','),...rows.map(p => csvFields.map(key => csvCell(
      key==='run_id'?model.run_id:key==='analysis_id'?model.analysis_id:key==='evidence_type'?model.evidence_label:p[key])).join(','))].join('\r\n')+'\r\n';
    return {csv,metadata:{schema_version:'1.0',run_id:model.run_id,analysis_id:model.analysis_id,
      report_revision:model.report_revision,evidence_type:model.evidence_label,dut:identity,
      figure_id:figureId,scope,point_count:rows.length,measurement_boundary:model.boundary,
      x_quantity:xKey(spec),y_quantity:spec.y_key,axis_bounds:scope==='visible'?bounds(spec):null,
      boundary_semantics:'inclusive numeric bounds; log bounds are exported in physical units',
      scope_description:scope==='selected'?'all referenced points in selected test traces; independent of zoom and log display omissions':
        'selected valid points plotted within both current axis ranges; nonpositive points excluded for log current',
      string_safety:'Spreadsheet formula prefixes in text cells are escaped with an apostrophe; evidence unchanged',
      view:clone(state)}};
  }
  function download(filename,content,type='application/json') {
    const url = URL.createObjectURL(new Blob([content],{type}));
    const link = document.createElement('a'); link.download = filename; link.href = url;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),1000);
  }
  function saveView() {
    return {...clone(state),evidence_type:model.evidence_label,kind:'exploratory-view',
      plotly_js_version:payload.plotly_js_version,measurement_boundary:model.boundary};
  }
  async function exportFigure(figureId,format='svg') {
    await pending;
    if (!['svg','png'].includes(format)) throw new Error('Unsupported figure format');
    const spec = specs.find(spec => spec.id === figureId), graph = graphs.get(figureId);
    const index = specs.findIndex(spec => spec.id === figureId)+1;
    const currentLayout = layout(spec), range = bounds(spec);
    currentLayout.xaxis.range = range.x && isLog(spec) ? range.x.map(Math.log10) : range.x;
    currentLayout.xaxis.autorange = !range.x;
    currentLayout.yaxis.range = range.y; currentLayout.yaxis.autorange = !range.y;
    const names = spec.series.filter(series => state.selected_series.includes(keyOf(series)) &&
      series.point_ids.some(id => plottedValue(spec, points.get(id))))
      .map(series => series.label).filter(Boolean).join('; ') || 'no qualified plotted conditions';
    const footer = [model.evidence_label+' | '+identity+' | Run '+model.run_id,
      'Analysis '+model.analysis_id+' | '+figureId+' | '+names,
      'Boundary: '+model.boundary+' | Aggregated points; exploratory view'].map(safe).join('<br>');
    Object.assign(currentLayout,{width:1180,height:710,autosize:false,
      title:{text:'Figure '+index+'. '+safe(spec.title),x:.06,font:{size:20}},
      margin:{l:80,r:30,t:85,b:150},annotations:[...(currentLayout.annotations??[]),{text:footer,x:0,y:-.24,xref:'paper',yref:'paper',
        xanchor:'left',yanchor:'top',align:'left',showarrow:false,font:{size:10,color:'#516677'}}]});
    const target = document.createElement('div'); target.style.cssText='position:fixed;left:-15000px;top:0;width:1180px;height:710px';
    document.body.append(target);
    try {
      await Plotly.newPlot(target,traces(spec),currentLayout,{displaylogo:false,staticPlot:true});
      return await Plotly.toImage(target,{format,width:1180,height:710,scale:format==='png'?2:1});
    } finally { Plotly.purge(target);target.remove(); }
  }
  function showPoint(pid) {
    const point = points.get(pid); if (!point) return;
    document.getElementById('point-picker').value = pid;
    document.getElementById('point-detail').textContent = (point.display_label ? point.display_label+' · ' : '')+
      'Aggregated point result '+pid+' · '+point.qualification+
      ' · '+(point.input_condition_label ?? 'requested '+point.vin_target_V+' V')+
      ' / '+point.iout_target_A+' A requested load. '+(point.reason ?? '');
    // Keep the same aggregated results available without pointer hover. The
    // separate raw table below retains individual queries and their timing.
    let measured=document.getElementById('point-measurements');
    if(!measured){measured=document.createElement('table');measured.id='point-measurements';
      document.getElementById('point-detail').after(measured);}
    measured.replaceChildren();
    const resultKind=model.evidence_label==='MEASURED'?'Measured':'Simulated';
    measured.setAttribute('aria-label',resultKind+' results for '+(point.display_label ?? pid));
    const measuredHead=document.createElement('thead'),measuredHeader=document.createElement('tr');
    for(const label of [resultKind+' result','Value']){const cell=document.createElement('th');
      cell.scope='col';cell.textContent=label;measuredHeader.append(cell);}
    measuredHead.append(measuredHeader);measured.append(measuredHead);
    const measuredBody=document.createElement('tbody');
    for(const [field,label,unit] of [['Vout_V','Output voltage','V'],['Iout_A','Output current','A'],
      ['Vin_V','Input voltage','V'],['Iin_A','Input current','A'],
      ['Pin_W','Input power','W'],['Pout_W','Output power','W'],['loss_W','Path loss','W'],
      ['efficiency_pct','Path efficiency','%'],['vout_error_pct','Output deviation','%']]){
      const row=document.createElement('tr'),heading=document.createElement('th'),value=document.createElement('td');
      heading.scope='row';heading.textContent=label;
      const useMilliamps=field.endsWith('_A')&&finite(point[field])&&Math.abs(point[field])<1;
      const measuredValue=useMilliamps?point[field]*1000:point[field];
      value.textContent=finite(measuredValue)?number(measuredValue)+' '+(useMilliamps?'mA':unit):'Not available';
      row.append(heading,value);measuredBody.append(row);
    }
    measured.append(measuredBody);
    let timing=document.getElementById('point-timing');
    if(!timing){timing=document.createElement('p');timing.id='point-timing';measured.after(timing);}
    timing.hidden=!finite(point.elapsed_s);
    timing.textContent=finite(point.elapsed_s)?'Measurement interval: '+number(point.elapsed_start_s)+'–'+
      number(point.elapsed_end_s)+' s; midpoint '+number(point.elapsed_s)+' s.':'';
    const container = document.getElementById('raw-evidence');container.replaceChildren();
    const rows = model.raw_samples?.[pid] ?? point.raw_samples ?? [];
    if (!rows.length) {
      const text = document.createElement('p');text.textContent='No raw samples are embedded for this point. '
        +(point.qualification==='not-run'||point.qualification==='setup-limited'?'This point was not acquired.':'Consult the companion run package if one is supplied.');
      container.append(text);return;
    }
    const explanation = document.createElement('p'); explanation.textContent=rows.length+' recorded raw sample(s), including available phases and timing. No samples are reconstructed from averages.';
    container.append(explanation);
    const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
    const table=document.createElement('table'),head=document.createElement('thead'),header=document.createElement('tr');
    for (const key of columns) {const cell=document.createElement('th');cell.textContent=key;header.append(cell);}
    head.append(header);table.append(head);const body=document.createElement('tbody');
    for (const row of rows) {const tr=document.createElement('tr');for(const key of columns){const td=document.createElement('td');
      const value=row[key];td.textContent=value===null||value===undefined?'':typeof value==='object'?JSON.stringify(value):String(value);tr.append(td);}body.append(tr);}
    table.append(body);container.append(table);
  }
  async function initialize() {
    if (typeof Plotly==='undefined') throw new Error('The embedded plotting library did not load');
    if (Plotly.version!==payload.plotly_js_version) throw new Error('Plotly version does not match the build manifest');
    for (const spec of specs) {
      const option=document.createElement('option');option.value=spec.id;option.textContent=spec.title;document.getElementById('metric-select').append(option);
      const figure=document.getElementById(spec.id);if (!figure) throw new Error('Missing figure anchor '+spec.id);
      const image=figure.querySelector('img');if(image) image.classList.add('static-fallback');
      const graph=document.createElement('div');graph.id='plot-'+spec.id;graph.className='interactive-chart';
      graph.setAttribute('aria-label',spec.title);graph.setAttribute('role','img');
      (figure.querySelector('figure') ?? figure).prepend(graph);graphs.set(spec.id,graph);
    }
    for(const [key,condition] of conditions) {
      const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.dataset.series=key;input.checked=true;
      input.addEventListener('change',()=>setView({selected_series:[...document.querySelectorAll('#trace-options input:checked')].map(el=>el.dataset.series)}).catch(fail));
      const swatch=document.createElement('span');swatch.className='trace-swatch';swatch.setAttribute('aria-hidden','true');
      swatch.style.color=condition.color;
      const line=document.createElement('span');line.className='trace-swatch-line';
      line.style.borderTopStyle=condition.dash==='solid'?'solid':condition.dash==='dot'?'dotted':'dashed';
      const marker=document.createElement('span');marker.className='trace-swatch-marker';
      marker.textContent=({circle:'●',square:'■',diamond:'◆',cross:'✚','triangle-up':'▲','triangle-down':'▼',x:'×'})[condition.symbol]??'●';
      swatch.append(line,marker);
      label.append(input,swatch,document.createTextNode(condition.label));document.getElementById('trace-options').append(label);
    }
    for(const [id,key] of [['metric-select','metric'],['x-select','x_key'],['hover-select','hovermode']]) {
      document.getElementById(id).addEventListener('change',event=>setView({[key]:event.target.value}).catch(fail));
    }
    document.getElementById('log-current').addEventListener('change',event=>setView({log_current:event.target.checked}).catch(fail));
    document.getElementById('reset-zoom').addEventListener('click',()=>resetZoom().catch(fail));
    document.getElementById('restore-view').addEventListener('click',()=>restoreDefaults().catch(fail));
    document.getElementById('save-view').addEventListener('click',async()=>{await pending;download('view-'+model.analysis_id+'.json',JSON.stringify(saveView(),null,2));});
    document.getElementById('print-view').addEventListener('click',async()=>{await pending;window.print();});
    const picker=document.getElementById('point-picker');
    for(const point of model.points){const option=document.createElement('option');option.value=point.point_id;
      option.textContent=point.display_label ? point.display_label+' · '+point.qualification :
        point.point_id+' · '+(point.input_condition_label ?? point.vin_target_V+' V')+
        ' / '+point.iout_target_A+' A · '+point.qualification;picker.append(option);}
    picker.addEventListener('change',()=>showPoint(picker.value));if(model.points.length)showPoint(model.points[0].point_id);
    await draw();
    for (const spec of specs) {
      const graph=graphs.get(spec.id);document.getElementById(spec.id).classList.add('chart-ready');
      graph.on('plotly_legendclick',event=>{if(updating)return false;const key=graph.data[event.curveNumber].meta.conditionKey;
        const selected=state.selected_series.includes(key)?state.selected_series.filter(item=>item!==key):[...state.selected_series,key];
        setView({selected_series:selected}).catch(fail);return false;});
      graph.on('plotly_legenddoubleclick',event=>{const key=graph.data[event.curveNumber].meta.conditionKey;
        setView({selected_series:state.selected_series.length===1&&state.selected_series[0]===key?[...conditions.keys()]:[key]}).catch(fail);return false;});
      graph.on('plotly_click',event=>{const pid=event.points?.find(point=>point.customdata)?.customdata;if(pid)showPoint(pid);});
      graph.on('plotly_relayout',event=>{
        if(updating)return;
        const next={...(state.ranges[spec.id]??{})};let changed=false;
        for(const dim of ['x','y']) {
          if(event[dim+'axis.autorange']===true){delete next[dim];changed=true;}
          let values=event[dim+'axis.range'];
          if(event[dim+'axis.range[0]']!==undefined)values=[event[dim+'axis.range[0]'],event[dim+'axis.range[1]']];
          if(values){next[dim]=dim==='x'&&isLog(spec)?values.map(value=>Math.pow(10,value)):values;changed=true;}
        }
        if(changed)state.ranges={...state.ranges,[spec.id]:next};
      });
    }
    document.querySelectorAll('.figure-actions[data-figure] button').forEach(button=>button.addEventListener('click',async()=>{
      try {await pending;const fid=button.parentElement.dataset.figure,action=button.dataset.action;
        if(action==='selected'||action==='visible'){const result=exportCSV(action,fid);download(fid+'-'+action+'.csv',result.csv,'text/csv;charset=utf-8');
          download(fid+'-'+action+'-metadata.json',JSON.stringify(result.metadata,null,2));}
        else {const url=await exportFigure(fid,action),link=document.createElement('a');link.href=url;link.download=fid+'-'+model.run_id+'.'+action;link.click();}
      }catch(error){fail(error);}
    }));
    if(payload.canonical_pdf){
      const link=document.createElement('a');link.href='report.pdf';link.textContent=' · Canonical PDF';
      document.getElementById('canonical-pdf-link')?.append(link);
      const primary=document.createElement('a');primary.href='report.pdf';primary.textContent='Download PDF';
      primary.className='pdf-download';document.getElementById('title-block-header')?.append(primary);
    }
    document.documentElement.dataset.reportReady='true';
  }
  window.dcdcReport={model,get state(){return clone(state);},setView,resetZoom,restoreDefaults,getSelectedPoints,
    exportCSV,exportFigure,saveView,showPoint,whenIdle:()=>pending,graphs};
  window.dcdcReport.readyPromise=initialize().catch(error=>{fail(error);throw error;});
})();
