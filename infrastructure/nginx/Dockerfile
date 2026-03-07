# Stage 1: Build franchisee-cms
FROM node:20-alpine AS build-cms
WORKDIR /app
COPY frontend/franchisee-cms/package*.json ./
RUN npm install --prefer-offline
COPY frontend/franchisee-cms/ ./
RUN npm run build

# Stage 2: Build user-portal
FROM node:20-alpine AS build-portal
WORKDIR /app
COPY frontend/user-portal/package*.json ./
RUN npm install --prefer-offline
COPY frontend/user-portal/ ./
RUN npm run build

# Stage 3: Nginx — serve both SPAs
FROM nginx:1.25-alpine
COPY --from=build-cms    /app/dist /usr/share/nginx/cms
COPY --from=build-portal /app/dist /usr/share/nginx/portal
COPY infrastructure/nginx/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
