FROM node:20-alpine AS frontend
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt fastapi uvicorn
COPY api/ ./api/
COPY dos_primary_segment/ ./dos_primary_segment/
COPY --from=frontend /app/web/dist ./web/dist
COPY start.sh ./
RUN chmod +x start.sh
ENV PORT=8000
EXPOSE 8000
CMD ["./start.sh"]
