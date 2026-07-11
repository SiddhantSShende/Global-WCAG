// Drives Pa11y + HTML_CodeSniffer with the WCAG2AAA standard — our main source
// of automated AAA checks. Usage: node run_pa11y.mjs <url>
import pa11y from 'pa11y';

const MARK = '__A11Y_RESULT__';
const url = process.argv[2];
const out = { engine: 'pa11y', url, status: 'error', data: null, error: null };

try {
  const results = await pa11y(url, {
    standard: 'WCAG2AAA',
    runners: ['htmlcs'],
    timeout: 60000,
    chromeLaunchConfig: { args: ['--no-sandbox'] },
  });
  out.data = results;                       // {documentTitle, pageUrl, issues:[...]}
  const hasError = (results.issues || []).some((i) => i.type === 'error');
  out.status = hasError ? 'violations' : 'clean';
} catch (e) {
  out.error = String((e && e.message) || e);
}
process.stdout.write('\n' + MARK + JSON.stringify(out) + '\n');
