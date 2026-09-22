FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS build
WORKDIR /src
ARG APP_VERSION
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN test -n "$APP_VERSION" \
    && npm run build -- --define "__APP_VERSION__='${APP_VERSION}'"
FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
COPY frontend/deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/panel/browser /usr/share/nginx/html
ARG DTC_BUILD_VERSION=dev
ARG DTC_VCS_REF=unknown
ARG DTC_BUILD_DATE=unknown
ARG DTC_LOCK_SHA256=unknown
LABEL org.opencontainers.image.version="$DTC_BUILD_VERSION" \
      org.opencontainers.image.revision="$DTC_VCS_REF" \
      org.opencontainers.image.created="$DTC_BUILD_DATE" \
      io.dynamic-thermal-charge.dependencies-lock-sha256="$DTC_LOCK_SHA256"
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
