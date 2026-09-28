# LeadFlow AI — Native Linux Deployment Guide

**Target OS:** Ubuntu 22.04 / 24.04 LTS  
**Architecture:** Nginx $\to$ systemd (FastAPI / Uvicorn) $\to$ PostgreSQL 16 + Redis 7 + Background Workers  
**Constraint:** Strict Native Execution (Zero Docker Dependencies)  

---

## Directory Structure

```text
deploy/
├── nginx/
│   └── leadflow.conf                    # Nginx reverse proxy, TLS, rate limits, security headers
├── systemd/
│   ├── leadflow-api.service             # Web API process supervisor (4 Uvicorn workers)
│   ├── leadflow-campaign-worker.service # Outbound email dispatch worker
│   ├── leadflow-enrichment-worker.service# Asynchronous lead enrichment worker
│   └── leadflow-maintenance-worker.service# Housekeeping, lease reaping, and DNS refresh
├── scripts/
│   ├── deploy.sh                        # Automated zero-downtime deployment runner
│   ├── migrate.sh                       # Alembic schema migration runner
│   ├── backup.sh                        # PostgreSQL compressed dump with SHA256 checksum
│   └── restore.sh                       # Verified database restoration drill
└── README.md
```

---

## Quick Setup on a Fresh Ubuntu Server

### 1. Install System Packages
```bash
sudo apt update && sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev \
    postgresql postgresql-contrib redis-server nginx \
    git curl ufw certbot python3-certbot-nginx
```

### 2. Configure Dedicated Service User
```bash
sudo useradd -r -s /bin/false -d /opt/leadflow-ai leadflow
sudo mkdir -p /opt/leadflow-ai /etc/leadflow /var/backups/leadflow
sudo chown -R leadflow:leadflow /opt/leadflow-ai /var/backups/leadflow
```

### 3. Deploy Code & Environment
```bash
cd /opt/leadflow-ai
# Clone or copy repository here
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create environment configuration
sudo cp .env.example /etc/leadflow/leadflow.env
sudo chmod 600 /etc/leadflow/leadflow.env
sudo chown leadflow:leadflow /etc/leadflow/leadflow.env
```

### 4. Install Systemd Units
```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now leadflow-api
sudo systemctl enable --now leadflow-campaign-worker
sudo systemctl enable --now leadflow-enrichment-worker
sudo systemctl enable --now leadflow-maintenance-worker
```

### 5. Configure Nginx & TLS
```bash
sudo cp deploy/nginx/leadflow.conf /etc/nginx/sites-available/leadflow.conf
sudo ln -sf /etc/nginx/sites-available/leadflow.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d outreach.yourdomain.com
```
