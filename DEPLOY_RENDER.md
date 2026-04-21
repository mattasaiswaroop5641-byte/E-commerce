# Deploy to Render

**ShadowMarket** is ready to deploy to Render for free.

## Quick Start - 3 Steps

### Step 1: Go to Render.com

- Visit [render.com](https://render.com)
- Sign up with GitHub account

### Step 2: Connect Your Repository

1. Click **"New +"** -> **"Web Service"**
2. Select **"Connect a repository"**
3. Search for and select `E-commerce`
4. Connect your GitHub

### Step 3: Configure and Deploy

1. **Name**: `shadowmarket` (or your choice)
2. **Environment**: `Python 3`
3. **Build Command**:

   ```bash
   pip install -r ecommerce/requirements.txt
   ```

4. **Start Command**:

   ```bash
   cd ecommerce && gunicorn app:app
   ```

5. **Region**: Choose closest to you
6. **Plan**: Select `Free`

### Step 4: Set Environment Variables

Click **"Advanced"** and add:

```text
SECRET_KEY = (generate a strong random string)
RESEND_API_KEY = (recommended for email; your Resend API key)
MAIL_FROM_NAME = ShadowMarket
MAIL_FROM_ADDRESS = onboarding@resend.dev (or your verified sender/domain)

# If you prefer SMTP instead of Resend:
# MAIL_SERVER = smtp.gmail.com
# MAIL_PORT = 587
# MAIL_USERNAME = your-email@gmail.com
# MAIL_PASSWORD = your-app-password
# MAIL_USE_TLS = true
```

Example strong key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Then click **"Create Web Service"**.

## You're Done

Render will automatically:

- Build your app
- Deploy it
- Give you a public URL: `https://shadow-market-7jrt.onrender.com/`

Your site will be live in ~2-3 minutes.

## Updates and Redeployment

Every time you push to GitHub:

```bash
git add .
git commit -m "Your changes"
git push origin main
```

Render will automatically redeploy.

## Notes

- Free plan has a 15-minute idle timeout (app goes to sleep if unused, wakes on first request)
- Database resets when app restarts (use paid PostgreSQL for persistence)
- Need paid plan for: always-on, custom domains, more CPU/RAM

---

**Questions?** Check [Render docs](https://render.com/docs).
