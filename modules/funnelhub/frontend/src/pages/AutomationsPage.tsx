import { Link } from "react-router-dom";
export default function AutomationsPage() {
  return <div className="page"><h1>Automations</h1><section className="card"><h2>Workflow builder — Planned</h2><p>A visual automation builder is not implemented.</p>
    <p>Existing periodic synchronization is configured in <Link to="/integrations">Integrations</Link>. Scheduled content is managed in <Link to="/compose">Compose</Link>.</p>
    <p>Automatic external synchronization and publishing start disabled in the test stack.</p></section></div>;
}
