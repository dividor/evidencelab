import pdfjsPackage from 'pdfjs-dist/package.json';

type Loader = typeof import('../utils/pdfjsLoader');

// Each test gets a fresh copy of the module, so a cached load does not leak.
const freshLoader = (): Loader => {
  let loader: Loader | undefined;
  jest.isolateModules(() => {
    loader = require('../utils/pdfjsLoader');
  });
  return loader as Loader;
};

const fakeLib = () => ({ GlobalWorkerOptions: { workerSrc: '' }, getDocument: jest.fn() });
const versionDir = `${window.location.origin}/pdfjs/${pdfjsPackage.version}/`;

describe('pdfjsLoader', () => {
  afterEach(() => {
    delete (window as any).pdfjsLib;
  });

  test('serves PDF.js from this site, under the installed version', () => {
    const { PDFJS_VERSION, pdfjsAssetUrl } = freshLoader();

    expect(PDFJS_VERSION).toBe(pdfjsPackage.version);
    expect(pdfjsAssetUrl('pdf.min.js')).toBe(`${versionDir}pdf.min.js`);
  });

  test('imports the library from this site and points it at its worker', async () => {
    const { loadPdfjs } = freshLoader();
    const lib = fakeLib();
    const importModule = jest.fn().mockResolvedValue(lib);

    await expect(loadPdfjs(importModule)).resolves.toBe(lib);

    expect(importModule).toHaveBeenCalledWith(`${versionDir}pdf.min.js`);
    expect(lib.GlobalWorkerOptions.workerSrc).toBe(`${versionDir}pdf.worker.min.js`);
    expect(window.pdfjsLib).toBe(lib);
  });

  test('loads the library once for several previews', async () => {
    const { loadPdfjs } = freshLoader();
    const importModule = jest.fn().mockResolvedValue(fakeLib());

    await Promise.all([loadPdfjs(importModule), loadPdfjs(importModule)]);
    await loadPdfjs(importModule);

    expect(importModule).toHaveBeenCalledTimes(1);
  });

  test('tries again after a failed load', async () => {
    const { loadPdfjs } = freshLoader();
    const lib = fakeLib();
    const importModule = jest
      .fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(lib);

    await expect(loadPdfjs(importModule)).rejects.toThrow('offline');
    await expect(loadPdfjs(importModule)).resolves.toBe(lib);
    expect(importModule).toHaveBeenCalledTimes(2);
  });

  test('opens documents without WebAssembly, with decoders from this site', () => {
    const { pdfjsDocumentOptions } = freshLoader();

    expect(pdfjsDocumentOptions('/api/pdf/doc-1')).toEqual({
      url: '/api/pdf/doc-1',
      useWasm: false,
      wasmUrl: versionDir,
    });
  });
});
