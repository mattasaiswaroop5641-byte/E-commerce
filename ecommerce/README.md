# ShadowMarket

A Flask ecommerce showcase with a richer catalog, grouped variants, cart and checkout flow, and hybrid recommendations.

## What Is Included

- Variant-aware catalog with grouped family cards
- Search, category browsing, product detail, cart, checkout, and order confirmation
- Login and signup with SQLite
- Email notifications for account signup, successful login, and order confirmation
- Real Stripe card checkout integration
- Order tracking page with status timeline
- Customer support ticket flow linked to orders/tracking
- Content-based recommendations
- Collaborative filtering recommendations
- Larger generated dataset with online product imagery and demo interactions

## Catalog Size

- `240` product rows
- `83` product families
- `8` storefront categories

## Tech Stack

- Python + Flask
- Flask-Login
- Flask-SQLAlchemy
- pandas
- scikit-learn
- Bootstrap 5

## Run The Project

### Local Development

```bash
cd ecommerce
pip install -r requirements.txt
copy ..\\.env.example .env
python app.py
```

### Email Setup (for signup/login/order emails)

Set these values in `.env`:

```bash
MAIL_FROM_NAME=ShadowMarket
MAIL_FROM_ADDRESS=onboarding@resend.dev
MAIL_SEND_LOGIN_NOTIFICATIONS=true
```

Then choose one of these options:

**Option A (Recommended): Resend**

```bash
RESEND_API_KEY=your_resend_api_key
```

In production, `MAIL_FROM_ADDRESS` should be a verified sender/domain in Resend.

**Option B: SMTP (Gmail example)**

```bash
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_USE_TLS=true
```

For Gmail, use an App Password (not your regular account password).

### Stripe Setup (for real card payments)

Set these values in `.env`:

```bash
STRIPE_PUBLISHABLE_KEY=pk_test_your_publishable_key
STRIPE_SECRET_KEY=sk_test_your_secret_key
STRIPE_CURRENCY=usd
```

Use Stripe test keys in development. Card checkout uses Stripe-hosted payment pages.

## Admin Panel (2FA)

The app includes a secure admin console for managing orders, support tickets, discounts, and admin-added products.

- Admin URL: `/admin/login`
- Authentication: `ADMIN_EMAIL` + password + TOTP (Google Authenticator / Authy)

Set these values in `.env` (or Render Environment Variables):

```bash
ADMIN_ENABLED=true
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD_HASH= # recommended (hashed)
ADMIN_TOTP_SECRET=   # base32 secret for TOTP
ADMIN_REQUIRE_2FA=true
```

Generate a password hash:

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('ChangeMe'))"
```

Generate a TOTP secret (base32):

```bash
python -c "import base64,secrets; print(base64.b32encode(secrets.token_bytes(20)).decode().replace('=',''))"
```

Then add the secret to your authenticator app using “Enter a setup key”.

### Docker Deployment

Build and run with Docker:

```bash
docker build -t ecommerce .
docker run -p 5000:5000 ecommerce
```

Or use Docker Compose:

```bash
docker-compose up --build
```

The app will be available at `http://localhost:5000`

## GitHub Actions CI/CD

This project includes automated testing and deployment via GitHub Actions:

- **Tests** run on Python 3.9, 3.10, and 3.11
- **Linting** checks code quality
- **Docker image** is built and optionally pushed to Docker Hub
- Triggered on push to `main` and `develop` branches

### Setting up Docker Hub deployment (optional):

1. Add these secrets to your GitHub repository settings:
   - `DOCKER_USERNAME`: Your Docker Hub username
   - `DOCKER_PASSWORD`: Your Docker Hub access token

2. The workflow will automatically build and push images on commits to main

## Deployment Options

### Heroku

```bash
heroku create your-app-name
git push heroku main
```

### Railway.app

Connect your GitHub repo and Railway will auto-deploy on each push.

### AWS/GCP/Azure

Use their container services with the provided Dockerfile.

## Additional Info

From the project folder:

```bash
python app.py
```

Then open `http://localhost:5000`.

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Project Structure

```text
ecommerce/
|-- app.py
|-- models.py
|-- forms.py
|-- requirements.txt
|-- data/
|   |-- generate_dataset.py
|   |-- products.csv
|   `-- interactions.csv
|-- recommenders/
|   |-- content_based.py
|   `-- collab.py
|-- templates/
|   |-- base.html
|   |-- index.html
|   |-- results.html
|   |-- product.html
|   |-- cart.html
|   |-- checkout.html
|   |-- login.html
|   |-- signup.html
|   `-- order_success.html
`-- static/
    |-- css/style.css
    |-- js/script.js
    `-- images/product-placeholder.svg
```

## Recommendation Notes

- Content-based recommendations use product title, brand, category, subcategory, variant data, and description text.
- Collaborative recommendations use interaction history with NMF plus popularity fallback.
- Homepage and product page recommendations are family-aware so the UI does not repeat the same variant family over and over.
