# Smart Tender frontend

Install and start the Vite app from this directory:

    npm ci
    npm run dev

The frontend API client uses one backend base URL. Copy .env.example to .env
and set VITE_API_BASE_URL when the backend is not at http://localhost:8000.

The app routes /admin/* to admin tender, collusion, and audit screens. Other
paths use the vendor routes. Session logout keeps the browser's device ID so
logging back in from the same browser does not create a false device warning.
