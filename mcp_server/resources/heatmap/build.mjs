import { build } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const here = new URL('./', import.meta.url);
const template = await readFile(new URL('./index.html', here), 'utf8');
const sdkLicense = await readFile(
  new URL('./node_modules/@modelcontextprotocol/ext-apps/LICENSE', here), 'utf8',
);
const { outputFiles } = await build({
  absWorkingDir: fileURLToPath(here),
  entryPoints: ['view.js'],
  bundle: true,
  format: 'esm',
  platform: 'browser',
  legalComments: 'inline',
  pure: ['console.debug'],
  minify: true,
  write: false,
});

const script = outputFiles[0].text.replaceAll(/<\/script/gi, '<\\/script');
const markup = template.replace('<!-- HEATMAPPER_SCRIPT -->', () => `<script type="module">${script}</script>`);
const dist = new URL('./dist/', here);
await mkdir(dist, { recursive: true });
await writeFile(new URL('./heatmap.html', dist), `${markup}\n<!-- MCP Apps SDK license\n${sdkLicense}-->\n`);
