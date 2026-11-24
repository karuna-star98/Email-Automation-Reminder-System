// Proxy /api/* to the FastAPI server so the browser never deals with CORS.
const API = process.env.API_URL || 'http://127.0.0.1:8000'
module.exports = { async rewrites() { return [{ source: '/api/:path*', destination: `${API}/api/:path*` }] } }
