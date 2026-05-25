# Process Forge — Deployment Guide

---

## PART 1 — Deploy to AWS EC2

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
3. Launch — note the **Public IPv4 address**

---

### Step 2 — Prepare your .pem key

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

### Step 4 — Create your .env file on the server

SSH in and create `/opt/processforge/.env`:

```bash
ssh -i ~/Downloads/processforge.pem ubuntu@<YOUR-EC2-IP>
cat > /opt/processforge/.env <<EOF
ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE
DEV_MODE=false
MODE_PIN=1234
CORS_ORIGINS=["http://<YOUR-EC2-IP>"]
EOF
```

**Change `1234` to a PIN your colleagues will use to switch modes.**

---

### Step 5 — Clone the repo and deploy

From your Mac (the repo and all code are in git — no manual file copying needed):

```bash
git clone https://github.com/grahamcrooks/processforge.git
cd processforge
./deploy.sh ubuntu@<YOUR-EC2-IP> ~/Downloads/processforge.pem
```

**Your app is now live at: `http://<YOUR-EC2-IP>`**

---

### Switching modes (for you or colleagues)

The **Mode bar** appears at the top of the app:
- 🟢 **Live mode** — real Claude API, uses tokens
- 🟡 **Mock mode** — sample data, zero cost

Click "Switch to Mock / Live" → enter the PIN → done. No SSH required.

---

### Deploying updates after any code change

```bash
./deploy.sh ubuntu@<YOUR-EC2-IP> ~/Downloads/processforge.pem
```

Builds frontend, uploads backend, restarts service — all in one command.

---

### Working from a different Mac

1. `git clone https://github.com/grahamcrooks/processforge.git`
2. Transfer `processforge.pem` securely (AirDrop, USB — never commit it to git)
3. `chmod 400 ~/path/to/processforge.pem`
4. `./deploy.sh ubuntu@<YOUR-EC2-IP> ~/path/to/processforge.pem`

The `.env` on the server (API key, PIN, CORS) stays in place between deploys.

---

---

## PART 2 — Add a Custom Domain (optional, do later)

### Step 1 — Buy a domain

Go to AWS Route 53 → Registered Domains → Register domain.
Suggested: `processforge.io` or `processforge.dev` (~$12-15/yr)

Or use any registrar (GoDaddy, Namecheap).

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

```bash
ssh -i ~/Downloads/processforge.pem ubuntu@<YOUR-EC2-IP>
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Follow the prompts — certbot updates nginx config automatically.
Certificate auto-renews every 90 days.

---

### Step 5 — Update CORS and nginx

Update `.env` on the server:

```bash
ssh -i ~/Downloads/processforge.pem ubuntu@<YOUR-EC2-IP>
nano /opt/processforge/.env
# Change CORS_ORIGINS to:
# CORS_ORIGINS=["https://yourdomain.com","https://www.yourdomain.com"]
sudo systemctl restart processforge
```

Update nginx:

```bash
sudo nano /etc/nginx/sites-available/processforge
# Change: server_name _;
# To:     server_name yourdomain.com www.yourdomain.com;
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
