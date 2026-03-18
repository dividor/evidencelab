const { createProxyMiddleware } = require('http-proxy-middleware');

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
