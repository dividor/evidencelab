const { readFileSync } = require('node:fs');
const { writeFile } = require('node:fs/promises');
const { chromium } = require('playwright');

async function createAdminSession(origin, email, password, destination) {
  const browser = await chromium.launch({ channel: 'chrome' });
  try {
    const context = await browser.newContext({ baseURL: origin });
    const page = await context.newPage();
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // The same sign-in request as the web app. The browser keeps the httpOnly cookie.
    const status = await page.evaluate(async ({ email, password }) => {
      const response = await fetch('/api/auth/cookie-login/login', {
        method: 'POST',
        body: new URLSearchParams({ username: email, password }),
      });
      return response.status;
    }, { email, password });
    if (status !== 204) throw new Error(`CI admin sign-in returned HTTP ${status}.`);

    await page.goto('/admin', { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: 'Administration', exact: true }).waitFor();
    const state = await context.storageState();
    await writeFile(destination, JSON.stringify(state), { mode: 0o600, flag: 'wx' });
  } finally {
    await browser.close();
  }
}

if (require.main === module) {
  const [origin, email, destination] = process.argv.slice(2);
  const password = readFileSync(0, 'utf8').trimEnd();
  createAdminSession(origin, email, password, destination).catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = { createAdminSession };
