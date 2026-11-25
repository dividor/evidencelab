const fs = require('fs');
const os = require('os');
const path = require('path');

const { copyPdfjs, pdfjsRoutes, installedPackageDir, FILES } = require('../../scripts/copy-pdfjs');

const makeTemp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'copy-pdfjs-'));

const fakePackage = (version, files = FILES.map(([source]) => source)) => {
  const dir = makeTemp();
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ version }));
  for (const file of files) {
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    fs.writeFileSync(path.join(dir, file), `contents of ${file}`);
  }
  return dir;
};

describe('copy-pdfjs', () => {
  test('serves each file at /pdfjs/<version>/, the modules under .js names', () => {
    const packageDir = fakePackage('9.9.9');

    expect(pdfjsRoutes(packageDir)).toEqual([
      ['/pdfjs/9.9.9/pdf.min.js', path.join(packageDir, 'build/pdf.min.mjs')],
      ['/pdfjs/9.9.9/pdf.worker.min.js', path.join(packageDir, 'build/pdf.worker.min.mjs')],
      [
        '/pdfjs/9.9.9/openjpeg_nowasm_fallback.js',
        path.join(packageDir, 'wasm/openjpeg_nowasm_fallback.js'),
      ],
      ['/pdfjs/9.9.9/jbig2_nowasm_fallback.js', path.join(packageDir, 'wasm/jbig2_nowasm_fallback.js')],
      ['/pdfjs/9.9.9/LICENSE', path.join(packageDir, 'LICENSE')],
    ]);
  });

  test('copies the files into the build under the same addresses', () => {
    const buildDir = makeTemp();

    const result = copyPdfjs(fakePackage('9.9.9'), buildDir);

    const target = path.join(buildDir, 'pdfjs', '9.9.9');
    expect(result.targetDir).toBe(target);
    expect(fs.readdirSync(target).sort()).toEqual([
      'LICENSE',
      'jbig2_nowasm_fallback.js',
      'openjpeg_nowasm_fallback.js',
      'pdf.min.js',
      'pdf.worker.min.js',
    ]);
    expect(fs.readFileSync(path.join(target, 'pdf.min.js'), 'utf8')).toBe(
      'contents of build/pdf.min.mjs'
    );
  });

  test('removes copies of other versions', () => {
    const buildDir = makeTemp();
    copyPdfjs(fakePackage('1.0.0'), buildDir);

    copyPdfjs(fakePackage('2.0.0'), buildDir);

    expect(fs.readdirSync(path.join(buildDir, 'pdfjs'))).toEqual(['2.0.0']);
  });

  test('fails, copying nothing, when a file is missing', () => {
    const buildDir = makeTemp();
    const sources = FILES.map(([source]) => source).filter((s) => s !== 'build/pdf.worker.min.mjs');

    expect(() => copyPdfjs(fakePackage('3.0.0', sources), buildDir)).toThrow(
      'pdfjs-dist 3.0.0 has no build/pdf.worker.min.mjs'
    );
    expect(fs.existsSync(path.join(buildDir, 'pdfjs'))).toBe(false);
  });

  test('the installed pdfjs-dist has every file the viewer needs', () => {
    const packageDir = installedPackageDir(path.resolve(__dirname, '..', '..'));

    const routes = pdfjsRoutes(packageDir);

    const { version } = require('pdfjs-dist/package.json');
    expect(routes).toHaveLength(FILES.length);
    expect(routes[0][0]).toBe(`/pdfjs/${version}/pdf.min.js`);
  });
});
