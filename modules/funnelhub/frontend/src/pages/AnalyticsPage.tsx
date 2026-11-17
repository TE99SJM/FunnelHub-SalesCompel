import SiteVisitors from "../components/SiteVisitors";
export default function AnalyticsPage() {
  return <div className="page"><header className="page-head"><div><h1>Analytics</h1><p className="muted">Connected website data. Empty connections display no invented metrics.</p></div></header>
    <SiteVisitors start="2015-08-14" end={new Date().toISOString().slice(0,10)} label="Available history" />
    <p className="muted">Channel history is available in Social Channels. A dedicated traffic-source and referral breakdown is planned.</p>
  </div>;
}
