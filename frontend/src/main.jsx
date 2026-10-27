import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

async function request(path, token, options = {}) {
  const response = await fetch(path, {...options, headers: {'X-Actor-Token': token, ...options.headers}});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}). Please retry.`);
  }
  return response;
}

function Badge({status}) { return <span className={`badge ${status.toLowerCase()}`}>{status}</span>; }

function App() {
  const [actors, setActors] = useState([]);
  const [token, setToken] = useState('alice-east');
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    fetch('/api/actors', {signal: controller.signal}).then(r => {
      if (!r.ok) throw new Error('Could not load actors.');
      return r.json();
    }).then(setActors).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [attempt]);
  const actor = actors.find(a => a.token === token);
  return <>
    <header className="topbar"><div className="brand"><span className="brand-icon">✓</span> Training platform <span className="separator">/</span><span>Admin console</span></div>
      <label className="actor-label">Acting as<select aria-label="Acting as" value={token} onChange={e => setToken(e.target.value)} disabled={!actors.length}>
        {actors.map(a => <option key={a.token} value={a.token}>{a.email} · {a.tenant}</option>)}
      </select></label></header>
    {error ? <main><div role="alert" className="notice error">{error} <button onClick={() => setAttempt(n=>n+1)}>Retry</button></div></main> :
      actor ? <Console key={token} actor={actor}/> : <main><p role="status">Loading actors…</p></main>}
  </>;
}

function Console({actor}) {
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('issue_date');
  const [direction, setDirection] = useState('desc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(5);
  const [refresh, setRefresh] = useState(0);
  const [list, setList] = useState({phase:'loading', items:[], total:0});
  const [courses, setCourses] = useState([]);
  const [course, setCourse] = useState('');
  const [courseError, setCourseError] = useState('');
  const [bulk, setBulk] = useState({phase:'idle'});
  const [exportState, setExportState] = useState({phase:'idle'});
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState({phase:'loading'});
  const [confirm, setConfirm] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState('');
  const pending = useRef(null);
  const busy = useRef(false);
  const exportBusy = useRef(false);
  const revokeBusy = useRef(false);
  const alive = useRef(true);
  const lifetime = useRef(new AbortController());
  const dialog = useRef(null);
  useEffect(() => () => { alive.current = false; lifetime.current.abort(); }, []);

  const params = () => new URLSearchParams({q:query, sort, direction});
  useEffect(() => {
    const controller = new AbortController();
    setList({phase:'loading',items:[],total:0});
    const p = new URLSearchParams({q:query,sort,direction,page:String(page),page_size:String(pageSize)});
    request(`/api/certificates?${p}`, actor.token, {signal:controller.signal})
      .then(r=>r.json()).then(data=>setList({...data,phase:'ready'}))
      .catch(e=> { if(e.name !== 'AbortError') setList({phase:'error',items:[],total:0,error:e.message}); });
    return ()=>controller.abort();
  }, [actor.token,query,sort,direction,page,pageSize,refresh]);

  useEffect(() => {
    const controller = new AbortController();
    setCourseError('');
    request('/api/courses',actor.token,{signal:controller.signal}).then(r=>r.json()).then(data=> {
      setCourses(data); setCourse(current=>current || String(data[0]?.id || ''));
    }).catch(e=> {if(e.name !== 'AbortError') setCourseError(e.message);});
    return ()=>controller.abort();
  }, [actor.token,refresh]);

  useEffect(() => {
    if (selected === null) return;
    const controller = new AbortController();
    setDetail({phase:'loading'}); setConfirm(false); setRevokeError('');
    if (dialog.current && !dialog.current.open) dialog.current.showModal();
    request(`/api/certificates/${selected}`,actor.token,{signal:controller.signal}).then(r=>r.json())
      .then(data=>setDetail({phase:'ready',data})).catch(e=> {if(e.name !== 'AbortError') setDetail({phase:'error',error:e.message});});
    return ()=>controller.abort();
  }, [selected,actor.token]);

  async function issue() {
    if(busy.current || !course) return;
    busy.current = true;
    if(!pending.current) pending.current = {key:crypto.randomUUID(),course_id:Number(course)};
    const operation = pending.current;
    setBulk({phase:'loading'});
    try {
      const response = await request('/api/bulk-issue',actor.token,{method:'POST',signal:lifetime.current.signal,
        headers:{'Content-Type':'application/json','Idempotency-Key':operation.key},body:JSON.stringify({course_id:operation.course_id})});
      const data = await response.json();
      if(!alive.current) return;
      pending.current = null; setBulk({phase:'ready',data}); setRefresh(n=>n+1);
    } catch(e) { if(alive.current && e.name !== 'AbortError') setBulk({phase:'error',error:e.message}); }
    finally { busy.current = false; }
  }

  async function download() {
    if(exportBusy.current) return;
    exportBusy.current = true; setExportState({phase:'loading'});
    try {
      const response = await request(`/api/certificates/export?${params()}`,actor.token,{signal:lifetime.current.signal});
      const blob = await response.blob();
      if(!alive.current) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = `${actor.tenant.toLowerCase()}-certificates.csv`;
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),30000);
      setExportState({phase:'ready'});
    } catch(e) { if(alive.current && e.name !== 'AbortError') setExportState({phase:'error',error:e.message}); }
    finally { exportBusy.current = false; }
  }

  async function revoke() {
    if(revokeBusy.current) return;
    revokeBusy.current = true; setRevoking(true); setRevokeError('');
    try {
      const response = await request(`/api/certificates/${selected}/revoke`,actor.token,{method:'POST',signal:lifetime.current.signal});
      const data = await response.json();
      if(!alive.current) return;
      setDetail({phase:'ready',data}); setConfirm(false); setRefresh(n=>n+1);
    } catch(e) {if(alive.current && e.name !== 'AbortError') setRevokeError(e.message);}
    finally {revokeBusy.current=false; if(alive.current) setRevoking(false);}
  }

  const totalPages = Math.max(1, Math.ceil(list.total/pageSize));
  return <main>
    <div className="heading"><div><p className="eyebrow">{actor.tenant} tenant <span>·</span> {actor.timezone}</p><h1>Certificates</h1><p className="muted">Review completions, issue certificates, and keep a clear record.</p></div>
      <button className="secondary" onClick={download} disabled={exportState.phase==='loading'}>{exportState.phase==='loading'?'Exporting…':'↓ Export CSV'}</button></div>
    {exportState.phase==='error' && <p role="alert" className="notice error">{exportState.error}</p>}
    {exportState.phase==='ready' && <p role="status" className="notice">CSV download started for the current search and sort.</p>}
    <div className="workspace"><section className="panel records" aria-label="Certificate list">
      <form className="search" onSubmit={e=>{e.preventDefault();setQuery(draft.trim());setPage(1);}}>
        <label className="sr-only" htmlFor="search">Search learner or serial number</label>
        <input id="search" type="search" placeholder="Search learner or serial number" value={draft} onChange={e=>setDraft(e.target.value)} maxLength={120}/>
        <button type="submit">Search</button>{query && <button type="button" className="text-button" onClick={()=>{setDraft('');setQuery('');setPage(1);}}>Clear</button>}
      </form>
      <div className="filters"><label>Sort by<select value={sort} onChange={e=>{setSort(e.target.value);setPage(1);}}>
        <option value="issue_date">Issue date</option><option value="learner_name">Learner</option><option value="course_title">Course</option><option value="serial_number">Serial number</option>
      </select></label><label>Order<select value={direction} onChange={e=>{setDirection(e.target.value);setPage(1);}}><option value="desc">Descending</option><option value="asc">Ascending</option></select></label>
        <span className="record-count">{list.phase==='ready'?`${list.total} certificates`:''}</span></div>
      {list.phase==='loading' ? <div className="empty" role="status">Loading certificates…</div> : list.phase==='error' ?
        <div className="empty" role="alert"><p>{list.error}</p><button onClick={()=>setRefresh(n=>n+1)}>Retry list</button></div> : !list.items.length ?
        <div className="empty"><div className="empty-symbol">⌕</div><h2>No certificates found</h2><p>Try another search, or issue certificates for a completed course.</p></div> :
        <div className="table-scroll"><table><thead><tr><th>Learner / serial</th><th>Course</th><th>Issued locally</th><th>Status</th><th><span className="sr-only">Details</span></th></tr></thead>
          <tbody>{list.items.map(row=><tr key={row.id}><td><strong>{row.learner_name}</strong><span className="serial" title={row.serial_number}>{row.serial_number}</span></td><td>{row.course_title}</td><td className="date">{row.issued_local}</td><td><Badge status={row.status}/></td><td><button className="text-button" aria-label={`View certificate for ${row.learner_name}`} onClick={()=>setSelected(row.id)}>View →</button></td></tr>)}</tbody></table></div>}
      <div className="pagination"><label>Rows<select value={pageSize} onChange={e=>{setPageSize(Number(e.target.value));setPage(1);}}><option>5</option><option>10</option><option>20</option></select></label>
        <span>Page {page} of {totalPages}</span><button className="secondary small" disabled={page<=1 || list.phase!=='ready'} onClick={()=>setPage(n=>n-1)}>Previous</button><button className="secondary small" disabled={page>=totalPages || list.phase!=='ready'} onClick={()=>setPage(n=>n+1)}>Next</button></div>
    </section>
    <aside className="panel issue-panel"><p className="eyebrow">Course completions</p><h2>Issue certificates</h2><p className="muted">Issue to every completed learner who has not already received a certificate.</p>
      <label>Course<select value={course} disabled={bulk.phase==='loading' || !!pending.current} onChange={e=>{setCourse(e.target.value);setBulk({phase:'idle'});}}>
        {courses.map(c=><option key={c.id} value={c.id}>{c.title} · {c.completed}/{c.enrolled} completed</option>)}
      </select></label>
      {courseError && <p role="alert" className="notice error">{courseError} <button onClick={()=>setRefresh(n=>n+1)}>Retry courses</button></p>}
      <button className="primary full" disabled={!course || !!courseError || bulk.phase==='loading'} onClick={issue}>{bulk.phase==='loading'?'Issuing certificates…':bulk.phase==='error'?'Retry same operation':'Issue certificates'}</button>
      <p className="hint">Incomplete and previously certified learners are skipped.</p>
      {bulk.phase==='loading' && <p role="status" className="notice">Processing this course. Please wait…</p>}
      {bulk.phase==='error' && <div role="alert" className="notice error"><p>{bulk.error}</p><p>The result is unconfirmed. Retry safely using the same operation.</p></div>}
      {bulk.phase==='ready' && <div className="operation-result"><h3 role="status">Operation complete</h3><div className="summary"><span><b>{bulk.data.summary.issued}</b> issued</span><span><b>{bulk.data.summary.skipped}</b> skipped</span><span><b>{bulk.data.summary.failed}</b> failed</span></div>
        <ul>{bulk.data.outcomes.map(row=><li key={row.learner_id}><div><strong>{row.learner_name}</strong><span>{row.reason?.replaceAll('_',' ') || row.serial_number}</span></div><span className={`outcome ${row.outcome}`}>{row.outcome}</span></li>)}</ul>
        <p className="hint operation-id">Operation {bulk.data.operation_id}</p></div>}
    </aside></div>
    <footer>Dates shown in {actor.timezone}. Export includes all matching records.</footer>
    {selected !== null && <dialog ref={dialog} aria-labelledby="detail-title" onCancel={e=>{e.preventDefault();if(!revoking)setSelected(null);}}>
      <div className="dialog-heading"><h2 id="detail-title">Certificate details</h2><button className="text-button" aria-label="Close certificate details" disabled={revoking} onClick={()=>setSelected(null)}>✕</button></div>
      {detail.phase==='loading'?<p role="status">Loading certificate…</p>:detail.phase==='error'?<p role="alert" className="notice error">{detail.error}</p>:<>
        <div className="detail-person"><h3>{detail.data.learner_name}</h3><Badge status={detail.data.status}/></div>
        <dl><dt>Course</dt><dd>{detail.data.course_title}</dd><dt>Serial number</dt><dd className="mono">{detail.data.serial_number}</dd><dt>Tenant</dt><dd>{detail.data.tenant_name}</dd><dt>Issued locally</dt><dd>{detail.data.issued_local}<small>{detail.data.timezone}</small></dd></dl>
        <h3 className="audit-title">Audit history</h3><ul className="audit">{detail.data.audits.map(event=><li key={event.event_type}><strong>{event.event_type==='ISSUED'?'Issued':'Revoked'}</strong><span>{event.actor}</span><small>{event.occurred_at} (UTC)</small></li>)}</ul>
        {revokeError && <p role="alert" className="notice error">{revokeError}</p>}
        {detail.data.status==='ACTIVE' && (confirm?<div className="confirm"><h3>Revoke this certificate?</h3><p>This certificate will no longer be valid. Its record and audit history will remain.</p><div className="actions"><button className="secondary" disabled={revoking} onClick={()=>setConfirm(false)}>Cancel</button><button className="danger" disabled={revoking} onClick={revoke}>{revoking?'Revoking…':'Confirm revocation'}</button></div></div>:<button className="danger-outline" onClick={()=>setConfirm(true)}>Revoke certificate</button>)}
        {detail.data.status==='REVOKED' && <p role="status" className="notice">This certificate has been revoked.</p>}
      </>}
    </dialog>}
  </main>;
}

createRoot(document.getElementById('root')).render(<App/>);
