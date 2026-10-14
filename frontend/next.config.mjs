/** @type {import('next').NextConfig} */
const nextConfig = {
    reactStrictMode: true,
    experimental: {
        // The /api/v1 rewrite proxies long answer streams: keep the connection above the 5-minute answer
        // budget (D3). Streams also need the backend's `Cache-Control: no-transform`, or Next's gzip
        // compression buffers them until they end (measured in M0.6d).
        proxyTimeout: 330_000,
    },
    images: {
        remotePatterns: [
            {
                protocol: 'https',
                hostname: 'images.unsplash.com',
            },
        ],
    },
    async rewrites() {
        return [
            {
                source: '/api/v1/:path*',
                destination: 'http://localhost:8000/api/v1/:path*', // Proxy to FastAPI
            },
        ];
    },
};

export default nextConfig;
