# OSINT Checker - Deployment & Production Guide

## Production Deployment

### Prerequisites

- Linux server (Ubuntu, CentOS, Debian)
- Python 3.8+
- Nginx (reverse proxy)
- SSL certificate (Let's Encrypt recommended)

### Deployment Steps

#### 1. System Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3 python3-pip python3-venv nginx supervisor

# Create application user
sudo useradd -m -s /bin/bash osint
sudo su - osint
```

#### 2. Application Deployment

```bash
# Clone/copy project
cd ~
git clone <repo-url> osint-checker
cd osint-checker

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

#### 3. Systemd Service File

Create `/etc/systemd/system/osint-checker.service`:

```ini
[Unit]
Description=OSINT Checker Service
After=network.target

[Service]
Type=notify
User=osint
WorkingDirectory=/home/osint/osint-checker
Environment="PATH=/home/osint/osint-checker/venv/bin"
ExecStart=/home/osint/osint-checker/venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind 127.0.0.1:5001 \
    --timeout 30 \
    --access-logfile /home/osint/osint-checker/logs/access.log \
    --error-logfile /home/osint/osint-checker/logs/error.log \
    wsgi:app

[Install]
WantedBy=multi-user.target
```

#### 4. Nginx Configuration

Create `/etc/nginx/sites-available/osint-checker`:

```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name osint.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name osint.yourdomain.com;

    # SSL certificates
    ssl_certificate /etc/letsencrypt/live/osint.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/osint.yourdomain.com/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript;

    # Proxy to Flask app
    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;

        # REST API timeouts
        proxy_connect_timeout 10s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }

    # Static files caching
    location /static/ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
```

#### 5. Enable and Start Service

```bash
# Create logs directory
sudo mkdir -p /home/osint/osint-checker/logs
sudo chown osint:osint /home/osint/osint-checker/logs

# Enable nginx site
sudo ln -s /etc/nginx/sites-available/osint-checker /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Enable and start service
sudo systemctl enable osint-checker
sudo systemctl start osint-checker
sudo systemctl status osint-checker

# View logs
sudo journalctl -u osint-checker -f
```

#### 6. SSL Certificate (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot certonly --nginx -d osint.yourdomain.com
```

### Monitoring & Maintenance

#### Health Monitoring

```bash
# Check service status
systemctl status osint-checker

# View logs
tail -f /home/osint/osint-checker/logs/error.log
tail -f /home/osint/osint-checker/logs/access.log

# Monitor with curl
watch -n 5 curl -s http://localhost:5001/api/health
```

#### Performance Tuning

Adjust Gunicorn workers based on CPU cores:

```python
# For 4-core system: workers = (2 * 4) + 1 = 9
workers = (2 * cpu_count) + 1
```

#### Updates

```bash
cd /home/osint/osint-checker
source venv/bin/activate
git pull origin main
pip install -r requirements.txt
systemctl restart osint-checker
```

## Docker Deployment (Alternative)

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application
COPY . .

# Create non-root user
RUN useradd -m osint && chown -R osint:osint /app
USER osint

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')"

# Run with gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "wsgi:app"]
```

### docker-compose.yml

```yaml
version: "3.8"

services:
  osint-checker:
    build: .
    ports:
      - "5000:5000"
    environment:
      FLASK_ENV: production
      SECRET_KEY: ${SECRET_KEY}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - osint-checker
    restart: unless-stopped
```

## Security Hardening

### Application Level

- Set `DEBUG=False` in production
- Use strong `SECRET_KEY` (generate with: `python -c "import secrets; print(secrets.token_hex(32))"`)
- Update dependencies regularly: `pip list --outdated`
- Run security audit: `safety check`

### System Level

- Firewall configuration (UFW):
  ```bash
  sudo ufw allow 22/tcp
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
  sudo ufw enable
  ```
- Fail2ban for rate limiting
- Regular security patches

### Logs & Monitoring

- Central log aggregation (ELK, Splunk)
- Error tracking (Sentry)
- Performance monitoring (Prometheus, Grafana)
- Set up alerts for:
  - High error rates
  - Response time degradation
  - Service restarts

## Scaling Considerations

### Horizontal Scaling

- Load balancer (HAProxy, Nginx upstream)
- Session affinity if needed
- Shared cache (Redis)

### Vertical Scaling

- Increase Gunicorn workers
- Optimize Python GC settings
- Use PyPy for performance

### Rate Limiting (Nginx)

```nginx
limit_req_zone $binary_remote_addr zone=osint_limit:10m rate=10r/s;

location /api/ {
    limit_req zone=osint_limit burst=20 nodelay;
}
```

## Backup & Disaster Recovery

```bash
# Automated backup
0 2 * * * tar -czf /backups/osint-checker-$(date +\%Y\%m\%d).tar.gz /home/osint/osint-checker

# Restore
tar -xzf osint-checker-20260324.tar.gz -C /home/osint/
```

## Troubleshooting

### High Memory Usage

```bash
# Check process memory
ps aux | grep gunicorn

# Reduce workers or tune Gunicorn
--max-requests 1000
--max-requests-jitter 100
```

### Connection Timeouts

- Increase Gunicorn timeout: `--timeout 60`
- Check Nginx upstream timeouts
- Verify database connections

### Permission Denied

```bash
sudo chown -R osint:osint /home/osint/osint-checker
sudo chmod 755 /home/osint/osint-checker
```

---

**Production deployment checklist:**

- [ ] SSL certificate installed
- [ ] Firewall configured
- [ ] Logs rotated
- [ ] Monitoring set up
- [ ] Backups automated
- [ ] Health checks passing
- [ ] Load testing completed
- [ ] Security audit passed
