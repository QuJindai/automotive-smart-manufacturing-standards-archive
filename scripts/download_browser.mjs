import { chromium } from 'playwright';
import fs from 'fs';

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const asset = JSON.parse(Buffer.concat(chunks).toString('utf8'));
const destination = process.argv[2];
if (!destination) throw new Error('destination is required');
const source = String(asset.source_url || '');
if (!source.startsWith('https://')) throw new Error('only HTTPS sources are allowed');
const evidence = asset.evidence && typeof asset.evidence === 'object' ? asset.evidence : {};
const landing = String(evidence.landing_url || evidence.referer || '');

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    locale: 'en-US',
    acceptDownloads: true,
  });
  const page = await context.newPage();
  if (landing.startsWith('https://')) {
    await page.goto(landing, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => null);
  } else {
    const origin = new URL(source).origin;
    await page.goto(origin, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => null);
  }
  await page.waitForTimeout(4000);

  let lastStatus = '-';
  let lastBytes = 0;
  for (let attempt = 1; attempt <= 4; attempt++) {
    const response = await page.request.get(source, {
      headers: {
        ...(landing.startsWith('https://') ? { referer: landing } : {}),
        accept: 'application/pdf,application/octet-stream,*/*;q=0.8',
      },
      timeout: 45000,
    }).catch(() => null);
    if (response) {
      lastStatus = String(response.status());
      const body = await response.body().catch(() => Buffer.alloc(0));
      lastBytes = body.length;
      if (response.ok() && body.length > 0) {
        fs.writeFileSync(destination, body);
        process.stdout.write(JSON.stringify({ status: response.status(), bytes: body.length, attempt }));
        process.exitCode = 0;
        break;
      }
    }
    if (attempt < 4) await page.waitForTimeout(8000);
  }
  if (!fs.existsSync(destination)) {
    throw new Error(`browser fetch failed status=${lastStatus} bytes=${lastBytes}`);
  }
} finally {
  await browser.close();
}
