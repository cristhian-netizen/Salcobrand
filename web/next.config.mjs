// Production: static export served at the root of the Salcobrand domain (CloudFront sends the
// backend paths to the Salcobrand app, same origin). Local dev: proxy those paths to a backend.
const isStaticExport = process.env.NEXT_OUTPUT === 'export';
const backend = (process.env.SALCOBRAND_BACKEND_URL || 'https://salcobrand-dev.neuramorphic.ai').replace(/\/$/, '');

export default {
  ...(isStaticExport ? { output: 'export' } : {}),
  skipTrailingSlashRedirect: true,
  distDir: process.env.NV_NEXT_DIST_DIR || '.next',
  // OneDrive can lock generated files on Windows. Opt-in for local validation only.
  cleanDistDir: process.env.NV_KEEP_BUILD_CACHE !== '1',
  ...(!isStaticExport ? {
    async rewrites() {
      return ['/api/:path*', '/uploads/:path*', '/catalog-images/:path*', '/static/:path*']
        .map(source => ({ source, destination: `${backend}${source}` }));
    },
  } : {}),
};
