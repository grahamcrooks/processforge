# Process Forge — Deployment Guide

---

## PART 1 — Deploy to AWS EC2 (IP address)

### Step 1 — Launch EC2 instance (AWS Console, 10 mins)

1. Go to EC2 → Launch Instance
2. Settings:
   - Name: `processforge`
   - AMI: **Ubuntu Server 22.04 LTS**
   - Instance type: **t3.small**
   - Key pair: Create new → download `processforge.pem`
   - Security group — add these inbound rules:
     | Port | Source    | Purpose       |
     |------|-----------|---------------|
     | 22   | Your IP   | SSH           |
     | 80   | 0.0.0.0/0 | HTTP          |
     | 443  | 0.0.0.0/0 | HTTPS (later) |
     | 8000 | 0.0.0.0/0 | Temp API test |
3. Launch — note the **Public IPv4 address**

---

### Step 2 — Prepare your .pem key (Mac terminal)

```bash
chmod 400 ~/Downloads/processforge.pem
```

---

### Step 3 — Set up the server (one time only)

```bash
ssh -i ~/Downloads/processforge.pem ubuntu@<YOUR-EC2-IP>
```

Once connected, run:

```bash
# Install dependencies
sudo apt update && sudo apt install -y python3-pip python3-venv nginx

# Create app directory
sudo mkdir -p /opt/processforge
sudo chown ubuntu:ubuntu /opt/processforge

# Set up systemd service
sudo tee /etc/systemd/system/processforge.service > /dev/null <<EOF
[Unit]
Description=Process Forge
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/processforge/backend
EnvironmentFile=/opt/processforge/.env
ExecStart=/opt/processforge/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable processforge

# Set up nginx to proxy port 80 → 8000
sudo tee /etc/nginx/sites-available/processforge > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 120s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/processforge /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

exit
```

---

### Step 4 — Create your .env file (on your Mac, in the project root)

```bash
cat > .env <<EOF
ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE
DEV_MODE=false
MODE_PIN=1234
CORS_ORIGINS=["http://<YOUR-EC2-IP>"]
EOF
```

**Change `1234` to a PIN your colleagues will use to switch modes.**

---

### Step 5 — Copy .env to the server

```bash
scp -i ~/Downloads/processforge.pem .env ubuntu@<YOUR-EC2-IP>:/opt/processforge/.env
```

---

### Step 6 — Add mode_pin to config.py

In `backend/config.py`, add this line to the Settings class:

```python
mode_pin: str = "1234"
```

---

### Step 7 — Add mode route to main.py

In `backend/main.py`, add these two lines after the existing router include:

```python
from api.routes.mode import router as mode_router
app.include_router(mode_router)
```

---

### Step 8 — Copy new frontend files

```bash
# From the project root
cp ModePanel.jsx      frontend/src/components/
cp ModePanel.css      frontend/src/components/
cp App.jsx            frontend/src/
cp ExtractionResultsPanel.jsx  frontend/src/components/
cp ExtractionResultsPanel.css  frontend/src/components/
cp mode.py            backend/api/routes/
```

---

### Step 9 — Deploy

```bash
./deploy.sh ubuntu@<YOUR-EC2-IP> ~/Downloads/processforge.pem
```

**Your app is now live at: `http://<YOUR-EC2-IP>`**

---

### Switching modes (for you or colleagues)

In the app, the **Mode bar** appears at the top of the page:
- 🟢 **Live mode** — real Claude API, uses tokens
- 🟡 **Mock mode** — sample data, zero cost

Click "Switch to Mock / Live" → enter the PIN → done.
No SSH required.

---

### Re-deploying after any code change

```bash
./deploy.sh ubuntu@<YOUR-EC2-IP> ~/Downloads/processforge.pem
```

That's it — builds frontend, uploads, restarts service automatically.

---

---

## PART 2 — Add a Custom Domain (do this later)

### Step 1 — Buy a domain

Go to AWS Route 53 → Registered Domains → Register domain.
Suggested: `processforge.io` or `processforge.dev` (~$12-15/yr)

Or use any registrar (GoDaddy, Namecheap) — just cheaper via Route 53
since it's already in AWS.

---

### Step 2 — Create a hosted zone

Route 53 → Hosted Zones → Create hosted zone → enter your domain.

---

### Step 3 — Point domain at your EC2

In the hosted zone, create an **A record**:
- Record name: (blank, for root domain)
- Record type: A
- Value: `<YOUR-EC2-IP>`
- TTL: 300

Also create:
- Record name: `www`
- Record type: CNAME
- Value: `yourdomain.com`

---

### Step 4 — Add HTTPS with Let's Encrypt (free)

SSH into your server:

```bash
ssh -i ~/Downloads/processforge.pem ubuntu@<YOUR-EC2-IP>

sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Follow the prompts — certbot automatically updates nginx config for HTTPS.
Certificate auto-renews every 90 days.

---

### Step 5 — Update CORS

Update your `.env` on the server:

```bash
ssh -i ~/Downloads/processforge.pem ubuntu@<YOUR-EC2-IP>
nano /opt/processforge/.env
```

Change:
```
CORS_ORIGINS=["https://yourdomain.com","https://www.yourdomain.com"]
```

Then restart:
```bash
sudo systemctl restart processforge
```

---

### Step 6 — Update nginx for your domain

```bash
sudo nano /etc/nginx/sites-available/processforge
```

Change `server_name _;` to `server_name yourdomain.com www.yourdomain.com;`

```bash
sudo nginx -t && sudo systemctl reload nginx
```

**Your app is now live at: `https://yourdomain.com`**

---

## Quick Reference

| Task | Command |
|---|---|
| Deploy update | `./deploy.sh ubuntu@<IP> ~/Downloads/processforge.pem` |
| Check service | `ssh ... "sudo systemctl status processforge"` |
| View logs | `ssh ... "journalctl -u processforge -f"` |
| Switch to mock | Use the Mode toggle in the app UI |
| Switch to live | Use the Mode toggle in the app UI |
| Restart server | `ssh ... "sudo systemctl restart processforge"` |
