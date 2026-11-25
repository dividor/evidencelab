const path = require('path');
const { createProxyMiddleware } = require('http-proxy-middleware');
const { installedPackageDir, pdfjsRoutes } = require('../scripts/copy-pdfjs');

module.exports = function (app) {
    const apiTarget = process.env.REACT_APP_API_URL;
    if (!apiTarget) {
        throw new Error('REACT_APP_API_URL is required for /api proxying.');
    }

    // Simple request logger middleware
    app.use((req, res, next) => {
        console.log(`[UI] ${req.method} ${req.url}`);
        next();
    });

    // PDF.js at the addresses the production build copies it to
    // (scripts/copy-pdfjs.js), served straight from node_modules.
    // The same base path the app uses (normalizeBasePath in src/config.ts).
    const rawBase = (process.env.REACT_APP_BASE_PATH || '').trim().replace(/\/+$/, '');
    const basePath = rawBase && !rawBase.startsWith('/') ? `/${rawBase}` : rawBase;
    const frontendDir = path.resolve(__dirname, '..');
    for (const [route, file] of pdfjsRoutes(installedPackageDir(frontendDir))) {
        app.get(`${basePath}${route}`, (req, res) => {
            res.type(path.extname(route) || 'text/plain').sendFile(file);
        });
    }

    // Proxy API calls to the backend in development.
    // Authentication is handled by session cookies (UI) or X-API-Key header
    // (external users / Swagger). The proxy does NOT inject API keys —
    // this matches production nginx behaviour.
    app.use(
        '/api',
        createProxyMiddleware({
            target: apiTarget,
            changeOrigin: true,
            pathRewrite: { '^/api': '' },
            proxyTimeout: 120000, // 120s timeout for slow API responses
            timeout: 120000, // 120s incoming socket timeout
        }),
    );
};
