import { useEffect, useState } from "react";
import { api, uploadWithProgress } from "../api/client";
import type { MediaItem } from "../types";

export default function MediaPage() {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const load = () => api.get<MediaItem[]>("/publish/media").then(setItems);
  useEffect(() => { load().catch(e => setError(String(e))); }, []);
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setError(""); setProgress(0);
    const form = new FormData(); Array.from(files).forEach(f => form.append("files", f));
    try { await uploadWithProgress("/publish/media", form, setProgress); await load(); }
    catch (e) {setError(e instanceof Error ? e.message : String(e));}
    finally {setProgress(null);}
  };
  const remove = async (item: MediaItem) => {
    if (!confirm(`Delete ${item.filename} from the test media library?`)) return;
    try {await api.del(`/publish/media/${item.id}`); await load();}
    catch (e) {setError(e instanceof Error ? e.message : String(e));}
  };
  return <div className="page"><header className="page-head"><div><h1>Media Library</h1><p className="muted">Stored persistently for drafts and publishing. Files are retained until you delete them.</p></div></header>
    <label className="card stack">Choose photos or videos<input type="file" multiple accept="image/*,video/*" disabled={progress !== null} onChange={e => {void upload(e.target.files); e.target.value = "";}} /></label>
    {progress !== null && <p role="status">Uploading {progress}%</p>}{error && <p role="alert" className="error-box">{error}</p>}
    <div className="grid-2">{items.map(item => <article className="card" key={item.id}><h2>{item.filename}</h2><p>{item.kind} · {(item.size / 1048576).toFixed(1)} MB</p>
      <div className="row"><button className="btn" onClick={() => api.download(`/publish/media/${item.id}/file`, item.filename).catch(e => setError(String(e)))}>Download</button>
      <button className="btn" onClick={() => remove(item)}>Delete</button></div></article>)}</div>
    {!items.length && <p>No uploaded media yet.</p>}
  </div>;
}
