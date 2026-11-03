# Admin frontend

The Vite app mounts AdminRoutes at /admin/*. Admin pages use the shared
src/auth/api.js client and the real session helpers in src/auth/token.js.
The admin shell links to tender management, collusion flags, and the audit log.
