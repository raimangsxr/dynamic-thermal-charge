FROM node:24-alpine AS build
WORKDIR /src
ARG APP_VERSION
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN test -n "$APP_VERSION" \
    && npm run build -- --define "__APP_VERSION__='${APP_VERSION}'"
FROM nginx:1.27-alpine
COPY frontend/deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/panel/browser /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
