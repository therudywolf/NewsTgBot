# Deployment Guide

This guide covers deploying NewsTgBot to various environments.

## Prerequisites

- Docker & Docker Compose 2.0+
- Domain name (for HTTPS)
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- LM Studio instance (for news summarization)

## Quick Start (Docker Compose)

### 1. Setup

```bash
git clone https://github.com/yourusername/NewsTgBot.git
cd NewsTgBot

# Copy and configure environment
cp .env.example .env
nano .env  # Edit with your tokens

# Create data directories
mkdir -p data logs
```

### 2. Configure .env

Required variables:

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_token_from_botfather

# Optional: Telethon (for channel parsing)
TELETHON_API_ID=your_api_id
TELETHON_API_HASH=your_api_hash
TELETHON_PHONE=+your_phone

# LLM summarization (optional)
LM_STUDIO_BASE_URL=http://localhost:1234
LM_STUDIO_API_TOKEN=your_token
LM_STUDIO_MODEL=model_name
```

### 3. Deploy

```bash
# Build and start services
docker compose up -d

# Check logs
docker compose logs -f

# Access admin panel
# http://localhost:8000
```

### 4. Verify

```bash
# Test bot is running
curl http://localhost:8000/api/status

# Restart bot worker (after token changes)
docker compose restart bot
```

## Production Deployment

### Environment Setup

```bash
# Create production directory
mkdir -p /opt/newstgbot
cd /opt/newstgbot

# Clone with specific version
git clone --branch v1.0.0 https://github.com/yourusername/NewsTgBot.git .

# Setup permissions
chown -R newstgbot:newstgbot .
chmod 700 .env data logs

# Create data directories
mkdir -p data logs
chmod 755 data logs
```

### SSL/TLS (Nginx Reverse Proxy)

```bash
# Install Nginx
sudo apt install nginx certbot python3-certbot-nginx

# Create nginx config
sudo tee /etc/nginx/sites-available/newstgbot << 'EOF'
server {
    listen 80;
    server_name newstgbot.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name newstgbot.example.com;

    ssl_certificate /etc/letsencrypt/live/newstgbot.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/newstgbot.example.com/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/newstgbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Get SSL certificate
sudo certbot certonly --nginx -d newstgbot.example.com
```

### Systemd Service

```bash
# Create service file
sudo tee /etc/systemd/system/newstgbot.service << 'EOF'
[Unit]
Description=NewsTgBot News Aggregator
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=newstgbot
WorkingDirectory=/opt/newstgbot
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down
Restart=always
RestartSec=10

Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable newstgbot
sudo systemctl start newstgbot
```

### Monitoring

```bash
# Check service status
sudo systemctl status newstgbot

# View logs
sudo journalctl -u newstgbot -f

# View docker logs
docker compose logs -f
```

## Kubernetes Deployment

### Prerequisites

- kubectl configured
- Helm 3+
- PersistentVolume support

### Deployment

```bash
# Create namespace
kubectl create namespace newstgbot

# Create ConfigMap and Secrets
kubectl create configmap newstgbot-config \
  --from-literal=AUTO_PARSE_ENABLED=true \
  --from-literal=CHECK_INTERVAL_SECONDS=3600 \
  -n newstgbot

kubectl create secret generic newstgbot-secrets \
  --from-literal=TELEGRAM_BOT_TOKEN=your_token \
  --from-literal=LM_STUDIO_API_TOKEN=your_token \
  -n newstgbot

# Apply deployment
kubectl apply -f k8s/deployment.yaml -n newstgbot
kubectl apply -f k8s/service.yaml -n newstgbot
kubectl apply -f k8s/ingress.yaml -n newstgbot

# Verify
kubectl get pods -n newstgbot
kubectl logs -f deployment/newstgbot-web -n newstgbot
```

## Backup & Recovery

### Automated Backup

```bash
#!/bin/bash
# backup.sh - Daily backup script

BACKUP_DIR=/backup/newstgbot
DOCKER_DATA=/opt/newstgbot/data

mkdir -p $BACKUP_DIR

# Backup database and config
tar czf $BACKUP_DIR/newstgbot-$(date +%Y%m%d-%H%M%S).tar.gz \
  --exclude='*.session' \
  --exclude='*.session-journal' \
  $DOCKER_DATA

# Keep only last 7 days
find $BACKUP_DIR -name '*.tar.gz' -mtime +7 -delete
```

### Recovery

```bash
# Stop services
docker compose down

# Restore database
cd /backup/newstgbot
tar xzf newstgbot-YYYYMMDD-HHMMSS.tar.gz -C /opt/newstgbot/

# Restart
cd /opt/newstgbot
docker compose up -d
```

## Security Checklist

- [ ] Change default passwords
- [ ] Setup firewall rules (only port 80/443 public)
- [ ] Enable automatic security updates
- [ ] Setup log rotation
- [ ] Regular backups configured
- [ ] SSL/TLS certificates valid
- [ ] `.env` file permissions: `600`
- [ ] Data directory permissions: `700`
- [ ] No hardcoded secrets in code
- [ ] Rate limiting enabled
- [ ] DDoS protection configured

## Troubleshooting

### Bot not responding

```bash
# Check bot is running
docker compose ps

# Check logs
docker compose logs bot

# Verify token
curl -X POST https://api.telegram.org/botYOUR_TOKEN/getMe

# Restart bot
docker compose restart bot
```

### Database locked

```bash
# Stop services
docker compose down

# Remove lock file
rm -f data/news_bot.db-journal

# Restart
docker compose up -d
```

### Memory issues

```bash
# Check resource usage
docker stats

# Reduce auto-parse limit in settings
# Reduce LLM context window
# Enable memory limits in docker-compose.yml
```

## Performance Tuning

### Docker Compose

```yaml
services:
  web:
    mem_limit: 512m
    cpus: 1
  bot:
    mem_limit: 256m
    cpus: 0.5
```

### Database Optimization

```sql
-- After initial setup
ANALYZE;
VACUUM;

-- Periodic maintenance
REINDEX;
```

## Support

- 📖 [README](README.md)
- 🤝 [Contributing](CONTRIBUTING.md)
- 🐛 [Bug Reports](https://github.com/yourusername/NewsTgBot/issues)

