import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { Button, Card, Badge, Stat } from "../components/ui.jsx";
import TopBar from "../components/TopBar.jsx";

export default function ReviewWorkbench() {
  const [params] = useSearchParams();
  const [jobId, setJobId] = useState(params.get("job") || "");
  const [queue, setQueue] = useState(null);
  const [openReview, setOpenReview] = useState(0);
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [rebuilt, setRebuilt] = useState(null);

  useEffect(() => { if (params.get("job")) load(params.get("job")); }, []); // eslint-disable-line

  async function load(id = jobId) {
    if (!id) return;
    const { ok, data } = await api(`/jobs/${id}/review-queue`);
    if (!ok || !data) { alert(data?.detail || "Could not load queue"); return; }
    setQueue(data.queue || []);
    setOpenReview(data.open_review || 0);
  }

  async function submitReview(e, sc) {
    e.preventDefault();
    const f = e.target;
    const body = {
      sc_num: sc, verdict: f.verdict.value, reviewer: f.reviewer.value,
      at_technique: f.at.value, rationale: f.rationale.value,
    };
    if (!body.rationale.trim()) { alert("A rationale is required."); return; }
    const { ok, data } = await api(`/jobs/${jobId}/reviews`, { method: "POST", body: JSON.stringify(body) });
    if (ok && data?.ok) load(); else alert(data?.detail || "Failed");
  }

  async function rebuild() {
    if (!jobId) return;
    const { data } = await api(`/jobs/${jobId}/rebuild-reports`, { method: "POST" });
    const rep = await api(`/jobs/${jobId}/reports`);
    setRebuilt({ status: data?.status || "done", reports: rep.data?.reports || [] });
  }

  const verified = (queue || []).filter((q) => q.review && q.status !== "needs_manual_review").length;
  const fails = (queue || []).filter((q) => q.status === "fail").length;
  const passes = (queue || []).filter((q) => q.status === "pass").length;
  const rows = (queue || []).filter((q) => (onlyOpen ? q.needs_review : true));

  const nav = <Link className="navlink" to="/">New audit</Link>;

  return (
    <>
      <TopBar sub="Review" nav={nav} />
      <main id="main" className="wrap stack" style={{ paddingTop: "1.75rem", paddingBottom: "2rem" }}>
        <Card>
          <span className="eyebrow">Human-review workbench</span>
          <h2 style={{ marginTop: ".25rem" }}>Close the “Needs Manual Review” rows</h2>
          <p className="muted" style={{ margin: ".4rem 0 0", maxWidth: "60ch" }}>
            Sign off criteria a machine can't prove — the only path to a defensible AAA verdict.
            A rationale is required; you can't override a confirmed machine failure.</p>
          <hr className="divider" />
          <div className="row">
            <div className="field" style={{ flex: 1, minWidth: 260, margin: 0 }}>
              <label htmlFor="job">Job ID</label>
              <input id="job" type="text" value={jobId} onChange={(e) => setJobId(e.target.value)}
                placeholder="paste the job id from a completed audit" />
            </div>
            <Button variant="primary" onClick={() => load()} style={{ alignSelf: "end" }}>Load queue</Button>
            <label className="check" style={{ alignSelf: "end", padding: ".55rem .8rem" }}>
              <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />
              <span>Only open</span>
            </label>
          </div>
        </Card>

        {queue && (
          <section className="stats">
            <Stat n={openReview} label="Awaiting review" tone="warn" />
            <Stat n={verified} label="Manually verified" tone="ok" />
            <Stat n={fails} label="Confirmed failures" tone="bad" />
            <Stat n={passes} label="Auto-passed" />
            <div className="stat" style={{ display: "flex", alignItems: "center" }}>
              <Button variant="primary" style={{ width: "100%" }} onClick={rebuild}>Rebuild reports</Button>
            </div>
          </section>
        )}

        {rebuilt && (
          <Card>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>Reports rebuilt with your verdicts</strong>
              <Badge status="pass">{rebuilt.status}</Badge>
            </div>
            <div className="reportgrid" style={{ marginTop: ".8rem" }}>
              {rebuilt.reports.map((r) => (
                <a className="rep" key={r.key} href={`/reports/${r.key}`} download>
                  <span className="ft ft-docx" style={{ width: 30, height: 30, fontSize: ".58rem" }}>
                    {r.key.split(".").pop().toUpperCase()}</span>
                  <span className="meta"><b>{r.key.split("/").pop()}</b></span>
                </a>
              ))}
            </div>
          </Card>
        )}

        {!queue && <p className="muted center" style={{ padding: "2rem" }}>Load a completed audit's job id to begin reviewing.</p>}

        <div className="stack">
          {rows.map((q) => (
            <Card key={q.sc_num}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <h3 style={{ fontSize: "1.05rem" }}>{q.sc_num} — {q.name}</h3>
                  <div className="row" style={{ gap: ".4rem", marginTop: ".4rem" }}>
                    <span className="tag">Level {q.level}</span>
                    <span className="tag">{q.principle}</span>
                    <span className="tag">testability: {q.testability}</span>
                    <Badge status={q.status} />
                  </div>
                </div>
              </div>

              {q.hints?.length ? (
                <div className="evidence" style={{ marginTop: ".8rem" }}>
                  {q.hints.map((h, i) => (
                    <div key={i} style={{ margin: ".35rem 0" }}>
                      • <strong>{h.engine}</strong> <span className="tag">{h.rule}</span> {h.description}
                      {h.url && <img src={h.url} alt={`Evidence for ${q.sc_num}`} />}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="faint" style={{ marginTop: ".6rem" }}>No automated findings — verify manually with assistive technology.</p>
              )}

              {q.review && (
                <p style={{ margin: ".7rem 0 0" }}>
                  <Badge status="pass">Reviewed: {q.review.verdict} · {q.review.reviewer}
                    {q.review.at_technique ? ` · ${q.review.at_technique}` : ""}</Badge>
                </p>
              )}

              <hr className="divider" style={{ margin: "1rem 0" }} />
              <form className="verdict-grid" onSubmit={(e) => submitReview(e, q.sc_num)}>
                <div className="field" style={{ margin: 0 }}>
                  <label>Verdict</label>
                  <select name="verdict" defaultValue="pass">
                    <option value="pass">Pass</option><option value="fail">Fail</option>
                    <option value="partial">Partial</option><option value="not_applicable">N/A</option>
                  </select>
                </div>
                <div className="field" style={{ margin: 0 }}><label>Reviewer</label><input name="reviewer" type="text" defaultValue="reviewer" /></div>
                <div className="field" style={{ margin: 0 }}><label>AT used</label><input name="at" type="text" placeholder="NVDA / VoiceOver" /></div>
                <div className="field" style={{ gridColumn: "1/-1", margin: 0 }}>
                  <label>Rationale (required)</label>
                  <input name="rationale" type="text" placeholder="Why this verdict — required for a defensible sign-off" />
                </div>
                <div><Button type="submit" variant="primary" size="sm" style={{ width: "100%" }}>Sign off</Button></div>
              </form>
            </Card>
          ))}
          {queue && rows.length === 0 && (
            <p className="muted center" style={{ padding: "2rem" }}>Nothing to show — try unchecking “Only open”.</p>
          )}
        </div>

        <footer className="foot">Global WCAG · manual verdicts are stamped into the report with reviewer + assistive-technology used.</footer>
      </main>
    </>
  );
}
