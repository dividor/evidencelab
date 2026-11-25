/**
 * Loads PDF.js for the document preview from this site.
 *
 * The PDF.js browser files are served at /pdfjs/<version>/, from the
 * pdfjs-dist version in package-lock.json: copied into the build after
 * `npm run build`, and served from node_modules by the development server
 * (scripts/copy-pdfjs.js). Nothing is fetched from another site, so the
 * page's Content-Security-Policy can allow scripts and workers from 'self'.
 */
import pdfjsPackage from 'pdfjs-dist/package.json';

import { APP_BASE_PATH } from '../config';

export const PDFJS_VERSION: string = pdfjsPackage.version;

/** Absolute address of a file in this build's copy of PDF.js. */
export const pdfjsAssetUrl = (file: string): string =>
  new URL(`${APP_BASE_PATH}/pdfjs/${PDFJS_VERSION}/${file}`, window.location.origin).href;

export type ModuleImporter = (url: string) => Promise<any>;

// webpackIgnore keeps webpack from bundling or rewriting this import: the
// browser loads the module from the address at run time.
const importFromUrl: ModuleImporter = (url) => import(/* webpackIgnore: true */ url);

let loading: Promise<any> | null = null;

/**
 * Load PDF.js once, point it at its worker, and keep it on window.pdfjsLib.
 * A failed load is not cached, so opening another preview tries again.
 */
export const loadPdfjs = (importModule: ModuleImporter = importFromUrl): Promise<any> => {
  if (window.pdfjsLib) {
    return Promise.resolve(window.pdfjsLib);
  }
  if (!loading) {
    loading = importModule(pdfjsAssetUrl('pdf.min.js'))
      .then((lib) => {
        lib.GlobalWorkerOptions.workerSrc = pdfjsAssetUrl('pdf.worker.min.js');
        window.pdfjsLib = lib;
        return lib;
      })
      .catch((err) => {
        loading = null;
        throw err;
      });
  }
  return loading;
};

/**
 * Options for getDocument. useWasm: false makes PDF.js decode JPEG 2000 and
 * JBIG2 images with its plain-JavaScript decoders (copied next to the library),
 * so the page needs no WebAssembly exception in its Content-Security-Policy.
 */
export const pdfjsDocumentOptions = (url: string) => ({
  url,
  useWasm: false,
  wasmUrl: pdfjsAssetUrl(''),
});
