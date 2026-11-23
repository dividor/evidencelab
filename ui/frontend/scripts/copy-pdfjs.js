/**
 * PDF.js for the document preview, served from this site at
 * /pdfjs/<version>/<file>, from the pdfjs-dist version in package-lock.json.
 *
 * - `npm run build` copies the files into build/pdfjs/<version>/ afterwards
 *   (the `postbuild` script), so they ship with the static site. Nothing is
 *   written into public/ or src/: the files are third-party build output.
 * - The development server serves the same addresses straight from
 *   node_modules (src/setupProxy.js uses pdfjsRoutes below).
 *
 * - The folder is named after the installed version, so a new version is a new
 *   address and the long cache on static files never serves a stale copy.
 * - The library and its worker are ES modules shipped as .mjs. They are served
 *   as .js, because module scripts must have a JavaScript content type and
 *   nginx (like some other servers) does not map .mjs to one. The viewer
 *   always sets the worker's address, so nothing refers to the .mjs names.
 * - The viewer opens documents with useWasm: false, so PDF.js decodes JPEG
 *   2000 and JBIG2 images with these plain-JavaScript decoders, and the page
 *   needs no WebAssembly exception in its Content-Security-Policy.
 *
 * Fails, rather than skipping, if any file is missing: the preview cannot work
 * without them.
 */
const fs = require('fs');
const path = require('path');

// [file in the pdfjs-dist package, name it is served under]
const FILES = [
  ['build/pdf.min.mjs', 'pdf.min.js'],
  ['build/pdf.worker.min.mjs', 'pdf.worker.min.js'],
  ['wasm/openjpeg_nowasm_fallback.js', 'openjpeg_nowasm_fallback.js'],
  ['wasm/jbig2_nowasm_fallback.js', 'jbig2_nowasm_fallback.js'],
  ['LICENSE', 'LICENSE'],
];

function installedPackageDir(frontendDir) {
  return path.dirname(require.resolve('pdfjs-dist/package.json', { paths: [frontendDir] }));
}

function packageVersion(packageDir) {
  return JSON.parse(fs.readFileSync(path.join(packageDir, 'package.json'), 'utf8')).version;
}

/** [address under the site root, absolute source file] for each file. */
function pdfjsRoutes(packageDir) {
  const version = packageVersion(packageDir);
  return FILES.map(([source, target]) => {
    const file = path.join(packageDir, source);
    if (!fs.existsSync(file)) {
      throw new Error(`pdfjs-dist ${version} has no ${source}`);
    }
    return [`/pdfjs/${version}/${target}`, file];
  });
}

/** Copy the files into <rootDir>/pdfjs/<version>/. */
function copyPdfjs(packageDir, rootDir) {
  const routes = pdfjsRoutes(packageDir);
  const version = packageVersion(packageDir);
  const targetDir = path.join(rootDir, 'pdfjs', version);

  fs.rmSync(path.join(rootDir, 'pdfjs'), { recursive: true, force: true });
  fs.mkdirSync(targetDir, { recursive: true });
  for (const [route, file] of routes) {
    fs.copyFileSync(file, path.join(rootDir, route));
  }
  return { version, targetDir, files: FILES.map(([, target]) => target) };
}

module.exports = { copyPdfjs, pdfjsRoutes, installedPackageDir, FILES };

if (require.main === module) {
  const frontendDir = path.resolve(__dirname, '..');
  const buildDir = path.join(frontendDir, 'build');
  if (!fs.existsSync(path.join(buildDir, 'index.html'))) {
    throw new Error(`No build in ${buildDir}: run this after react-scripts build`);
  }
  const { version, targetDir, files } = copyPdfjs(installedPackageDir(frontendDir), buildDir);
  console.log(`[copy-pdfjs] Copied PDF.js ${version} (${files.length} files) to ${targetDir}`);
}
