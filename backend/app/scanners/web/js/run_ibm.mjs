// Drives IBM Equal Access (accessibility-checker) — ACT-aligned cross-check.
// Usage: node run_ibm.mjs <url>
import aChecker from 'accessibility-checker';

const MARK = '__A11Y_RESULT__';
const url = process.argv[2];
const out = { engine: 'ibm-equal-access', url, status: 'error', data: null, error: null };

try {
  const res = await aChecker.getCompliance(url, 'a11y-audit');
  const report = (res && res.report) || res || {};
  out.data = report;                        // {results:[...], summary, nls, ...}
  const results = report.results || [];
  out.status = results.some((r) => r.level === 'violation') ? 'violations' : 'clean';
} catch (e) {
  out.error = String((e && e.message) || e);
} finally {
  try { await aChecker.close(); } catch { /* ignore */ }
}
process.stdout.write('\n' + MARK + JSON.stringify(out) + '\n');
