FROM node:25-alpine

WORKDIR /app

# Copy package files
COPY package.json ./

# Clear npm cache and install dependencies
RUN npm cache clean --force && \
    npm install --legacy-peer-deps && \
    apk add --no-cache moreutils

# Copy project files
COPY . .

# Note: datasources.config.json is mounted as a volume in docker-compose.yml

# Expose port
EXPOSE 3000

# Start development server
CMD ["npm", "start"]
