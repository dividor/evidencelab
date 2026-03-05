const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function (app) {
    const apiTarget = process.env.REACT_APP_API_URL;
    if (!apiTarget) {
        throw new Error('REACT_APP_API_URL is required for /api proxying.');
    }

    // API key injected server-side so it never reaches the browser
    const apiSecretKey = process.env.API_SECRET_KEY;

    // Simple request logger middleware
    app.use((req, res, next) => {
        console.log(`[UI] ${req.method} ${req.url}`);
        next();
    });

    // Proxy API calls to the backend in development
    app.use(
        '/api',
        createProxyMiddleware({
            target: apiTarget,
            changeOrigin: true,
            pathRewrite: { '^/api': '' },
            proxyTimeout: 120000, // 120s timeout for slow API responses
            timeout: 120000, // 120s incoming socket timeout
            onProxyReq: (proxyReq) => {
                if (apiSecretKey) {
                    proxyReq.setHeader('X-API-Key', apiSecretKey);
                }
            },
        }),
    );
};
