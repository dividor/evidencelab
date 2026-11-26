const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { once } = require('node:events');
const { mkdtemp, readFile, rm, stat } = require('node:fs/promises');
const { createServer } = require('node:http');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const test = require('node:test');
const { createAdminSession } = require('./admin-session.cjs');

test('stores a private session after opening an authenticated admin screen', async (t) => {
  const email = 'ux-admin@example.org';
  const password = randomUUID();
  const session = `test_session=${randomUUID()}`;
  const server = createServer(async (request, response) => {
    if (request.url === '/api/auth/cookie-login/login' && request.method === 'POST') {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const form = new URLSearchParams(Buffer.concat(chunks).toString());
      if (form.get('username') !== email || form.get('password') !== password) {
        response.writeHead(401).end();
        return;
      }
      response.writeHead(204, { 'Set-Cookie': `${session}; Path=/; Secure; HttpOnly` }).end();
      return;
    }
    if (request.url === '/admin' && request.headers.cookie !== session) {
      response.writeHead(403).end();
      return;
    }
    const heading = request.url === '/admin' ? 'Administration' : 'Home';
    response.writeHead(200, { 'Content-Type': 'text/html' }).end(`<h1>${heading}</h1>`);
  });
  server.listen(0, 'localhost');
  t.after(() => server.close());
  await once(server, 'listening');
  const origin = `http://localhost:${server.address().port}`;
  const directory = await mkdtemp(join(tmpdir(), 'ux-admin-test-'));
  t.after(() => rm(directory, { recursive: true }));
  const destination = join(directory, 'admin.json');

  await createAdminSession(origin, email, password, destination);
  const state = JSON.parse(await readFile(destination, 'utf8'));
  assert.equal(state.cookies[0].name, 'test_session');
  assert.equal(state.cookies[0].httpOnly, true);
  assert.equal((await stat(destination)).mode & 0o777, 0o600);
  await assert.rejects(createAdminSession(origin, email, '', destination), /HTTP 401/);
});
