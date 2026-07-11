// Drives axe-core (Deque) via @axe-core/playwright against a live page.
// Usage: node run_axe.mjs <url>
// Emits: line beginning "__A11Y_RESULT__" followed by a JSON envelope.
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const MARK = '__A11Y_RESULT__';
const url = process.argv[2];
const out = { engine: 'axe-core', url, status: 'error', data: null, error: null };

let browser;
try {
  browser = await chromium.launch({ args: ['--no-sandbox'] });
  // Authenticated scan: reuse the captured storage state if provided.
  const storageState = process.env.A11Y_STORAGE_STATE || undefined;
  const context = await browser.newContext({
    viewport: { width: 1366, height: 900 },
    ...(storageState ? { storageState } : {}),
  });
  const page = await context.newPage();
  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
  } catch {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  }
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'wcag2aaa', 'best-practice'])
    .analyze();
  out.data = results;                       // {violations, passes, incomplete, inapplicable}
  out.status = (results.violations && results.violations.length) ? 'violations' : 'clean';
} catch (e) {
  out.error = String((e && e.message) || e);
} finally {
  if (browser) await browser.close().catch(() => {});
}
process.stdout.write('\n' + MARK + JSON.stringify(out) + '\n');
