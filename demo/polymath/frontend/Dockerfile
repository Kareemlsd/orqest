# Polymath frontend — dev-mode Dockerfile (default for docker-compose).
# Hot reload via `next dev`. For a production build use Dockerfile.prod below
# or swap the target in docker-compose.yml.
FROM node:22-alpine

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=development

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
