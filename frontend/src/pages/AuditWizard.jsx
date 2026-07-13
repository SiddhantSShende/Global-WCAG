import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Button, Card, SectionTitle } from "../components/ui.jsx";
import TopBar from "../components/TopBar.jsx";
import { Website, Android, Apple, Play, Check } from "../components/icons.jsx";

const TARGETS = [
  { value: "web", title: "Website", desc: "Domain → subdomains → crawl → 4-engine scan.", Icon: Website },
  { value: "android", title: "Android app", desc: "Emulator + Google Accessibility Test Framework.", Icon: Android },
  { value: "ios", title: "iOS app", desc: "Simulator + XCUITest accessibility audit (macOS).", Icon: Apple },
];
const APP_HINT = {
  android: "Runs on an Android emulator host (Windows/WHPX or Linux/KVM). Provide a debug/Simulator build for full coverage.",
  ios: "Runs on a macOS worker (Apple SLA). Requires a Simulator .app build — a store .ipa won't install.",
};
const PHASES = ["Discover", "Crawl", "Scan", "Evidence", "Report"];

function activePhase(step, status) {
  const s = (step || "").toLowerCase();
  if (status === "done") return 5;
  if (s.includes("discover")) return 0;
  if (s.includes("crawl")) return 1;
  if (s.includes("scan") || s.includes("audit")) return 2;
  if (s.includes("evidence")) return 3;
  if (s.includes("build") || status === "building") return 4;
  return 0;
}

// Normalize anything a user might type/paste (bare host, *.wildcard, host:port,
// or a full URL) down to a bare hostname — mirrors backend subdomains._bare_host.
function bareHost(value) {
  const v = (value || "").trim().toLowerCase();
  if (!v) return "";
  try {
    return new URL(v.includes("://") ? v : `https://${v}`).hostname;
  } catch {
    return v.split("/")[0].split("@").pop().replace(/^\*\./, "").split(":")[0];
  }
}

function groupReports(reports) {
  const groups = {};
  for (const r of reports || []) {
    const name = r.key.split("/").pop();
    const m = name.match(/WCAG_(\d\.\d)_(A|AA|AAA)(_ACR)?\.(docx|xlsx|pdf)/);
    if (!m) continue;
    const combo = `WCAG ${m[1]} · ${m[2]}`;
    const fmt = m[3] ? "acr" : m[4];
    (groups[combo] ||= []).push({ fmt, url: "/reports/" + r.key });
  }
  return groups;
}

export default function AuditWizard() {
  const [ttype, setTtype] = useState("web");
  const [form, setForm] = useState({
    url: "https://example.com", allow: "", authorized: true,
    loginUrl: "", user: "", pass: "", appref: "", appAuth: true,
  });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);
  const [reports, setReports] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let fails = 0;
    const tick = async () => {
      const res = await api("/jobs/" + jobId);
      if (!alive) return;
      if (res.ok && res.data && res.data.status) {
        fails = 0;
        const data = res.data;
        setJob(data);
        if (data.status === "done") {
          const r = await api("/jobs/" + jobId + "/reports");
          if (!alive) return;
          if (r.ok) setReports(r.data?.reports || []);
          else setError("The audit finished, but its reports couldn't be loaded — "
                        + (r.data?.detail || `HTTP ${r.status}`));
          setBusy(false);
          return;
        }
        if (data.status === "error") { setBusy(false); return; }
      } else {
        // Non-OK response or unreachable backend: never spin forever.
        fails += 1;
        if (fails >= 5) {
          setError(res.data?.detail
                   || `Lost contact with the server (HTTP ${res.status}). Is the audit API running?`);
          setBusy(false);
          return;
        }
      }
      setTimeout(tick, 2000);
    };
    tick();
    return () => { alive = false; };
  }, [jobId]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setReports(null); setJob(null); setError(null);
    const body = { target_type: ttype };
    if (ttype === "web") {
      body.target_ref = form.url.trim();
      body.authorized = form.authorized;
      // URL-only flow: the entered site's own host is always in scope; the
      // optional field only ADDS extra subdomains. Dedupe + normalize.
      const targetHost = bareHost(body.target_ref);
      const extras = form.allow.split(",").map(bareHost).filter(Boolean);
      body.scope_allowlist = [...new Set([targetHost, ...extras].filter(Boolean))];
      if (form.user || form.pass) body.inputs = { login_url: form.loginUrl.trim() || undefined, credentials: { username: form.user, password: form.pass } };
    } else {
      body.target_ref = form.appref.trim() || "app";
      body.authorized = form.appAuth;
      body.inputs = { package: body.target_ref, bundle_id: body.target_ref };
    }
    const res = await api("/jobs", { method: "POST", body: JSON.stringify(body) });
    if (!res.ok || !res.data?.job_id) {
      alert(res.data?.detail || `Could not start (HTTP ${res.status})`);
      setBusy(false); return;
    }
    setJobId(res.data.job_id);
  }

  const phase = job ? activePhase(job.step, job.status) : 0;
  const groups = reports ? groupReports(reports) : {};

  const nav = (<>
    <a className="navlink" href="#audit">New audit</a>
    <Link className="navlink" to="/review">Review workbench</Link>
  </>);

  return (
    <>
      <TopBar sub="Audit" nav={nav} />
      <main id="main">
        <section className="hero">
          <div className="blob a" aria-hidden="true" />
          <div className="blob b" aria-hidden="true" />
          <div className="wrap">
            <span className="pill"><b>WCAG 2.0 · 2.1 · 2.2</b> Level A · AA · AAA — evidence-backed</span>
            <h1>Accessibility compliance,<br /><span className="grad-text">proven, not guessed.</span></h1>
            <p className="lead">Audit websites, Android and iOS apps against every WCAG version and level.
              Real screenshot evidence, multi-engine findings, and honest verdicts — nothing fabricated.</p>
          </div>
        </section>

        <div className="wrap stack" style={{ paddingBottom: "2rem" }} id="audit">
          <Card pad="lg">
            <form onSubmit={submit}>
              <SectionTitle num="1">Choose what to audit</SectionTitle>
              <div className="choices" role="radiogroup" aria-label="Target type">
                {TARGETS.map(({ value, title, desc, Icon }) => (
                  <label className="choice" key={value}>
                    <input type="radio" name="ttype" value={value}
                      checked={ttype === value} onChange={() => setTtype(value)} />
                    <span className="body">
                      <span className="ic" aria-hidden="true"><Icon /></span>
                      <h3>{title}</h3><p>{desc}</p>
                    </span>
                    <span className="tick" aria-hidden="true"><Check width="13" /></span>
                  </label>
                ))}
              </div>

              <hr className="divider" />
              <SectionTitle num="2">Provide the details</SectionTitle>

              {ttype === "web" ? (
                <>
                  <div className="field">
                    <label htmlFor="url">Domain URL</label>
                    <input id="url" type="url" value={form.url} onChange={set("url")} placeholder="https://example.com" />
                  </div>
                  <p className="hint" style={{ marginTop: ".4rem" }}>
                    That's all we need — we audit the site at this URL. Add extra subdomains below only if you want them included too.</p>
                  <details style={{ marginTop: ".9rem" }}>
                    <summary style={{ cursor: "pointer", fontWeight: 650, fontSize: ".9rem", color: "var(--text-muted)" }}>
                      Additional in-scope subdomains (optional)</summary>
                    <div className="field" style={{ marginTop: ".75rem" }}>
                      <label htmlFor="allow">Extra in-scope hosts</label>
                      <input id="allow" type="text" value={form.allow} onChange={set("allow")} placeholder="app.example.com, docs.example.com" />
                      <p className="hint">Leave blank to audit just the site above. Discovery stays deny-by-default — we never touch a host that isn't the target or explicitly listed here.</p>
                    </div>
                  </details>
                  <label className="check" style={{ marginTop: "1rem" }}>
                    <input type="checkbox" checked={form.authorized} onChange={set("authorized")} />
                    <span>I attest I own, or am authorized to test, this domain.</span>
                  </label>
                  <details style={{ marginTop: "1rem" }}>
                    <summary style={{ cursor: "pointer", fontWeight: 650, fontSize: ".9rem", color: "var(--text-muted)" }}>
                      Authenticated scan (optional)</summary>
                    <div className="grid-2" style={{ marginTop: ".75rem" }}>
                      <div className="field"><label htmlFor="lu">Login URL</label><input id="lu" type="url" value={form.loginUrl} onChange={set("loginUrl")} placeholder="https://example.com/login" /></div>
                      <div className="field"><label htmlFor="un">Username</label><input id="un" type="text" autoComplete="off" value={form.user} onChange={set("user")} /></div>
                      <div className="field"><label htmlFor="pw">Password</label><input id="pw" type="password" autoComplete="off" value={form.pass} onChange={set("pass")} /></div>
                    </div>
                    <p className="hint">Credentials go to the secret vault (never the database) and are purged after the job.</p>
                  </details>
                </>
              ) : (
                <>
                  <div className="field">
                    <label htmlFor="appref">App package / bundle id</label>
                    <input id="appref" type="text" value={form.appref} onChange={set("appref")} placeholder="com.example.app" />
                  </div>
                  <p className="hint">{APP_HINT[ttype]}</p>
                  <label className="check">
                    <input type="checkbox" checked={form.appAuth} onChange={set("appAuth")} />
                    <span>I attest I am authorized to test this application.</span>
                  </label>
                </>
              )}

              <div className="row" style={{ marginTop: "1.5rem" }}>
                <Button type="submit" variant="primary" disabled={busy}>
                  <Play /> {busy ? "Working…" : "Start audit"}
                </Button>
                <span className="faint">Generates 6 headline reports (A &amp; AAA) + AA cuts &amp; VPAT ACR — in .docx and .xlsx.</span>
              </div>
            </form>
          </Card>

          {job && (
            <Card pad="lg">
              <SectionTitle num="3">{job.status === "done" ? "Scan complete" : job.status === "error" ? "Scan stopped" : "Auditing…"}</SectionTitle>
              <div className="steps" aria-hidden="true">
                {PHASES.map((p, i) => (
                  <span key={p} className={`s ${i < phase ? "done" : i === phase ? "active" : ""}`} title={p} />
                ))}
              </div>
              <div className="row">
                {busy && <span className="spinner" aria-hidden="true" />}
                <strong aria-live="polite">Status: {job.status}</strong>
              </div>
              {job.step && <p className="muted" aria-live="polite" style={{ margin: ".4rem 0 0" }}>{job.step}</p>}
              {job.error_detail && <p className="badge st-fail" style={{ marginTop: "1rem" }}>{job.error_detail.split("\n")[0]}</p>}
              <p className="faint" style={{ marginTop: ".75rem" }}>Job <code>{jobId}</code></p>
            </Card>
          )}

          {error && (
            <Card pad="lg">
              <SectionTitle num="!">Something went wrong</SectionTitle>
              <p className="badge st-fail" style={{ margin: 0 }}>{error}</p>
            </Card>
          )}

          {reports && Object.keys(groups).length === 0 && !error && (
            <Card pad="lg">
              <p className="muted" style={{ margin: 0 }}>
                The audit completed but produced no downloadable reports. Check the job status above.</p>
            </Card>
          )}

          {reports && Object.keys(groups).length > 0 && (
            <Card pad="lg">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div className="section-title" style={{ margin: 0 }}>
                  <span className="num" style={{ background: "var(--ok-bg)", color: "var(--ok)" }}>✓</span>
                  <h2>Reports ready</h2>
                </div>
                <Link className="btn btn-sm" to={`/review?job=${jobId}`}>Open review workbench →</Link>
              </div>
              <p className="muted" style={{ margin: ".6rem 0 1.2rem" }}>
                Each WCAG version × level as a narrative <b>.docx</b>, a machine-friendly <b>.xlsx</b>, and a VPAT 2.5 <b>ACR</b>.
                Unproven criteria are honestly marked “Needs Manual Review”.</p>
              <div className="stats" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(230px,1fr))" }}>
                {Object.entries(groups).map(([combo, files]) => (
                  <div className="stat" key={combo} style={{ padding: "1.1rem" }}>
                    <div className="l" style={{ fontSize: ".72rem", textTransform: "uppercase", letterSpacing: ".08em" }}>{combo}</div>
                    <div className="row" style={{ gap: ".4rem", marginTop: ".7rem" }}>
                      {files.sort((a, b) => a.fmt.localeCompare(b.fmt)).map((f) => (
                        <a className="rep" key={f.fmt} href={f.url} download style={{ padding: ".4rem .6rem" }}>
                          <span className={`ft ${f.fmt === "acr" ? "ft-acr" : "ft-" + f.fmt}`}
                            style={{ width: 30, height: 30, fontSize: ".6rem" }}>{f.fmt.toUpperCase()}</span>
                        </a>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>

        <footer className="foot wrap">
          Global WCAG · evidence-backed accessibility auditing · reports carry engine versions for reproducibility.
        </footer>
      </main>
    </>
  );
}
