// PM2 process file for the Next.js UI. Started by video-downloader-web.service via
// `pm2-runtime`, with a private PM2_HOME, so it is isolated from other PM2 apps.
module.exports = {
  apps: [
    {
      name: "video-downloader-web",
      script: "server.js",
      cwd: "/opt/video-downloader/current/frontend",
      exec_mode: "fork",
      instances: 1,
      max_memory_restart: "400M",
      env: {
        NODE_ENV: "production",
        HOSTNAME: "127.0.0.1",
        PORT: process.env.VD_WEB_PORT || "3010",
      },
    },
  ],
};
