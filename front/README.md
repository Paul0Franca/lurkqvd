# Front do LurkQVD

React 19 + TypeScript + Vite + Tailwind 4. Veja o [README do projeto](../README.md) para instalar e usar.

```bash
npm install
npm run dev      # http://localhost:5173 (API em VITE_API_URL, padrão http://localhost:8000)
npm run build    # checagem de tipos + build de produção em dist/
npm run lint
```

No Docker, o build usa `VITE_API_URL=/api` e o nginx (`nginx/default.conf`) repassa `/api/` para a API.
