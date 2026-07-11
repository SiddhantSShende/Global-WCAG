// Drives Lighthouse (Google) — accessibility category only.
// Usage: node run_lighthouse.mjs <url>
import lighthouse from 'lighthouse';
import * as chromeLauncher from 'chrome-launcher';

const MARK = '__A11Y_RESULT__';
const url = process.argv[2];
const out = { engine: 'lighthouse', url, status: 'error', data: null, error: null };

let chrome;
try {
  chrome = await chromeLauncher.launch({ chromeFlags: ['--headless=new', '--no-sandbox'] });
  const runnerResult = await lighthouse(url, {
    port: chrome.port,
    onlyCategories: ['accessibility'],
    output: 'json',
    logLevel: 'silent',
  });
  const lhr = runnerResult.lhr;
  const cat = lhr.categories.accessibility;
  // Keep only audits referenced by the accessibility category, to bound size.
  const audits = {};
  for (const ref of cat.auditRefs) {
    const a = lhr.audits[ref.id];
    if (a) audits[ref.id] = { id: a.id, title: a.title, score: a.score,
      scoreDisplayMode: a.scoreDisplayMode, description: a.description,
      details: a.details };
  }
  out.data = { score: cat.score, audits };
  const failed = Object.values(audits).filter(
    (a) => a.score === 0 && a.scoreDisplayMode !== 'notApplicable'
      && a.scoreDisplayMode !== 'informative' && a.scoreDisplayMode !== 'manual');
  out.status = failed.length ? 'violations' : 'clean';
} catch (e) {
  out.error = String((e && e.message) || e);
} finally {
  // chrome-launcher's kill() runs a SYNCHRONOUS rmSync that throws EPERM on
  // Windows (Chrome hasn't released its temp dir) — a sync throw slips past an
  // async .catch(), so guard it here or it crashes before we emit the envelope.
  if (chrome) { try { chrome.kill(); } catch { /* Windows temp cleanup */ } }
}
process.stdout.write('\n' + MARK + JSON.stringify(out) + '\n');
