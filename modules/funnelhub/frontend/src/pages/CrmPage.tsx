import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";

type RecordRow = { Id: string; Name?: string; FirstName?: string; LastName?: string; AccountId?: string; Email__c?: string; Compat_Text__c?: string };
type Status = { configured: boolean; pending: number; errors: {contact_id: number; error: string}[]; mode: string };

export default function CrmPage({ accounts = false }: { accounts?: boolean }) {
  const [rows, setRows] = useState<RecordRow[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const load = async () => {
    setBusy(true); setError("");
    try {
      setStatus(await api.get<Status>("/crm/status"));
      setRows((await api.get<{records: RecordRow[]}>(accounts ? "/crm/accounts" : "/crm/contacts")).records);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  useEffect(() => { setRows([]); setEditing(null); void load(); }, [accounts]);
  const save = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const data = {Name: name.trim(), Compat_Text__c: note || null};
      if (editing) await api.patch(`/crm/accounts/${editing}`, data);
      else await api.post("/crm/accounts", data);
      setEditing(null); await load();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };
  const sync = async () => {
    setBusy(true);
    try { await api.post("/crm/sync"); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };
  return <div className="page">
    <header className="page-head"><div><h1>{accounts ? "Accounts" : "CRM"}</h1><p className="muted">Persistent records powered by SalesCompel.</p></div>
      <button className="btn" disabled={busy} onClick={() => void load()}>Refresh</button></header>
    {error && <p className="error-box" role="alert">{error}</p>}
    {status && <section className="card"><p>{status.pending} contact updates awaiting CRM synchronization.</p>
      <button className="btn" disabled={busy || !status.configured} onClick={sync}>Sync contacts</button>
      {status.errors.map(e => <p key={e.contact_id} role="alert">Contact {e.contact_id}: {e.error}</p>)}</section>}
    <p className="muted">{accounts ? "Company accounts are linked from contacts during synchronization." : <>Manage names and email relationships in <Link to="/contacts">Contacts</Link>. This view shows the synchronized CRM records.</>}</p>
    {accounts && <button className="btn btn-primary" onClick={() => {setEditing(""); setName(""); setNote("");}}>New account</button>}
    {editing !== null && accounts && <form className="card stack" onSubmit={save}>
      <label>Account name<input required maxLength={255} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>Note<input maxLength={80} value={note} onChange={e => setNote(e.target.value)} /></label>
      <button className="btn btn-primary" disabled={busy}>Save account</button><button className="btn" type="button" onClick={() => setEditing(null)}>Cancel</button>
    </form>}
    {busy && <p role="status">Loading CRM…</p>}
    <div className="card table-wrap"><table className="table"><thead><tr><th>Name</th><th>{accounts ? "Note" : "Email"}</th><th>CRM ID</th>{accounts && <th>Actions</th>}</tr></thead>
      <tbody>{rows.map(row => <tr key={row.Id}><td data-label="Name">{row.Name || `${row.FirstName || ""} ${row.LastName || ""}`}</td><td data-label={accounts ? "Note" : "Email"}>{accounts ? row.Compat_Text__c : row.Email__c}</td><td data-label="CRM ID">{row.Id}</td>
        {accounts && <td data-label="Actions"><button className="btn" onClick={() => {setEditing(row.Id); setName(row.Name || ""); setNote(row.Compat_Text__c || "");}}>Edit</button></td>}</tr>)}</tbody></table>
      {!busy && !error && !rows.length && <p>No records yet.</p>}</div>
    <p className="muted small">Early test integration · one owner workspace · first 2,000 CRM records shown.</p>
  </div>;
}
