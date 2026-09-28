# LeadFlow AI — Production Deployment Guide (Native Linux / No Docker)

**Target OS:** Ubuntu 22.04 / 24.04 LTS  
**Architecture:** Nginx $\to$ systemd (FastAPI / Uvicorn) $\to$ PostgreSQL 16 + Redis 7 + Dedicated Workers  
**Zero Container Policy:** Runs natively via Linux systemd processes.

---

## 1. System Requirements & Provisioning

- **CPU**: Minimum 2 vCPUs (4 vCPUs recommended for concurrent enrichment).
- **RAM**: Minimum 4GB (8GB recommended if running Playwright headless Chromium fallback).
- **Disk**: 40GB+ NVMe SSD.
- **Network**: Static IPv4 address with reverse DNS (rDNS) configured.

---

## 2. Step-by-Step Production Setup

### Step 1: Create Dedicated Service User
```bash
sudo useradd -r -s /bin/bash -m -d /opt/leadflow-ai leadflow
sudo usermod -aG systemd-journal leadflow
```

### Step 2: Install System Packages
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev \
    postgresql postgresql-contrib \
    redis-server \
    nginx \
    git curl ufw certbot python3-certbot-nginx \
    build-essential libpq-dev
```

### Step 3: Configure PostgreSQL
```bash
sudo systemctl enable --now postgresql

# Create leadflow database user and production database
sudo -u postgres psql -c "CREATE USER leadflow WITH PASSWORD 'CHANGE_THIS_SECURE_PASSWORD' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE leadflow_production OWNER leadflow;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE leadflow_production TO leadflow;"
```

### Step 4: Configure Redis
```bash
# Enable Redis supervised by systemd
sudo sed -i 's/^supervised no/supervised systemd/' /etc/redis/redis.conf
sudo systemctl restart redis-server
sudo systemctl enable redis-server

# Verify Redis
redis-cli ping # Expected: PONG
```

### Step 5: Setup Application Directory & Python Virtual Environment
```bash
cd /opt/leadflow-ai
# Clone or copy application repository into /opt/leadflow-ai
sudo chown -R leadflow:leadflow /opt/leadflow-ai

# Switch to leadflow user
sudo -u leadflow -i
cd /opt/leadflow-ai

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# If Playwright browser fallback is required:
playwright install chromium
playwright install-deps
```

### Step 6: Configure Environment Variables
Create the production environment file `/etc/leadflow/leadflow.env`:
```bash
sudo mkdir -p /etc/leadflow
sudo cp /opt/leadflow-ai/.env.example /etc/leadflow/leadflow.env
```
Edit `/etc/leadflow/leadflow.env` with production secrets:
```ini
ENVIRONMENT=production
DEBUG=False
APP_NAME=LeadFlow AI
APP_VERSION=2.0.0

SECRET_KEY=generate_with_openssl_rand_hex_32
DASHBOARD_API_KEY=generate_strong_random_key

DATABASE_URL=postgresql://leadflow:CHANGE_THIS_SECURE_PASSWORD@127.0.0.1:5432/leadflow_production
REDIS_URL=redis://127.0.0.1:6379/0

HOST=127.0.0.1
PORT=8000

LOG_LEVEL=INFO
ALLOWED_HOSTS=outreach.yourdomain.com,127.0.0.1
CORS_ORIGINS=https://outreach.yourdomain.com
```
Lock permissions down:
```bash
sudo chown leadflow:leadflow /etc/leadflow/leadflow.env
sudo chmod 600 /etc/leadflow/leadflow.env
```

### Step 7: Run Database Migrations
```bash
sudo -u leadflow bash -c "
cd /opt/leadflow-ai
source .venv/bin/activate
alembic upgrade head
"
```

### Step 8: Install Systemd Services
Copy systemd service definitions:
```bash
sudo cp /opt/leadflow-ai/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable services to start automatically on system boot
sudo systemctl enable leadflow-api.service
sudo systemctl enable leadflow-campaign-worker.service
sudo systemctl enable leadflow-enrichment-worker.service
sudo systemctl enable leadflow-maintenance-worker.service

# Start all services
sudo systemctl start leadflow-api.service
sudo systemctl start leadflow-campaign-worker.service
sudo systemctl start leadflow-enrichment-worker.service
sudo systemctl start leadflow-maintenance-worker.service
```

### Step 9: Configure Nginx Reverse Proxy & TLS
```bash
sudo cp /opt/leadflow-ai/deploy/nginx/leadflow.conf /etc/nginx/sites-available/leadflow.conf
sudo sed -i 's/outreach.yourdomain.com/YOUR_ACTUAL_DOMAIN.COM/g' /etc/nginx/sites-available/leadflow.conf
sudo ln -sf /etc/nginx/sites-available/leadflow.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Verify syntax and reload
sudo nginx -t
sudo systemctl reload nginx

# Obtain TLS certificate via Let's Encrypt Certbot
sudo certbot --nginx -d YOUR_ACTUAL_DOMAIN.COM
```

### Step 10: Configure Firewall (UFW)
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https
sudo ufw enable
```

### Step 11: Verify Health & Run Smoke Tests
```bash
# Check local API health
curl -s http://127.0.0.1:8000/health/live
curl -s http://127.0.0.1:8000/health/ready

# Run automated smoke test
/opt/leadflow-ai/scripts/production_smoke_test.sh https://YOUR_ACTUAL_DOMAIN.COM
```
