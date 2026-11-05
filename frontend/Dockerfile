# Build stage runs on the CONNECTED preparation machine (or with a local npm cache); runtime image is fully offline.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
ARG VITE_DEMO_HINT=0
ENV VITE_DEMO_HINT=$VITE_DEMO_HINT
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV ONLYOFFICE_ORIGIN=http://localhost:8080
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
