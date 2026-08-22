# ThinkDome Console

The operator console is a Node.js/TypeScript application built with Vite and
React. It talks to the Python control plane through the `/v1` API and does not
contain database access or sandbox credentials.

```bash
npm install
npm run dev       # local console at http://localhost:5173
npm run build     # emits ../thinkdome/static/console
```

The established dashboard at `/` remains the default theme. The compiled Node
console is available at `/console` for incremental evaluation.
