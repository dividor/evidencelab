import { build } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const here = new URL('./', import.meta.url);
const template = await readFile(new URL('./index.html', here), 'utf8');
const fonts = [
  { packageName: 'open-sans', family: 'Open Sans', weight: '400' },
  { packageName: 'open-sans', family: 'Open Sans', weight: '600' },
  { packageName: 'poppins', family: 'Poppins', weight: '600' },
];
const faces = await Promise.all(fonts.map(async ({ packageName, family, weight }) => {
  const file = new URL(`./node_modules/@fontsource/${packageName}/files/${packageName}-latin-${weight}-normal.woff2`, here);
  return { family, weight, data: await readFile(file, 'base64') };
}));
const licenses = await Promise.all(
  ['@modelcontextprotocol/ext-apps', '@fontsource/open-sans', '@fontsource/poppins'].map(async name => {
    const license = await readFile(new URL(`./node_modules/${name}/LICENSE`, here), 'utf8');
    return `${name}\n${license}`;
  }),
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
const markup = template
  .replace('<!-- STOCK_FONTS -->', () => JSON.stringify(faces))
  .replace('<!-- HEATMAPPER_SCRIPT -->', () => `<script type="module">${script}</script>`);
const dist = new URL('./dist/', here);
await mkdir(dist, { recursive: true });
await writeFile(new URL('./heatmap.html', dist), `${markup}\n<!-- Bundled licenses\n${licenses.join('\n')}-->\n`);
