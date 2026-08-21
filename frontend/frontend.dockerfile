# ---------- Build Stage ----------
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# ---------- Runtime Stage ----------
FROM nginx:alpine

# Vue Build Output
COPY --from=build /app/dist /usr/share/nginx/html

# Nginx Config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# nginx laedt ein erneuertes Zertifikat nicht von selbst - es haelt die alte
# Datei offen, bis es neu geladen wird. Ohne diese Schleife laeuft der Server
# nach einem Renewal bis zum naechsten Neustart mit dem abgelaufenen
# Zertifikat. `nginx -s reload` ist unterbrechungsfrei (alte Worker bedienen
# laufende Requests aus), 6 h ist damit unkritisch oft.
CMD ["/bin/sh", "-c", "while :; do sleep 6h & wait ${!}; nginx -s reload; done & nginx -g 'daemon off;'"]
