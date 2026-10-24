# Front do LurkQVD: build estático (Vite) servido pelo nginx, que também repassa /api para a API.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# o navegador fala com a API pelo mesmo endereço do front (sem CORS): /api -> serviço api
ENV VITE_API_URL=/api
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/seguranca.conf /etc/nginx/seguranca.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
