---
layout: default
---

# ShadowMarket - E-Commerce Platform

A Flask-based e-commerce application with product recommendations and checkout flow.

## 🚀 Quick Start

### Local Development
```bash
cd ecommerce
pip install -r requirements.txt
python app.py
```

### Docker
```bash
docker build -t ecommerce .
docker run -p 5000:5000 ecommerce
```

## 📋 Features

- ✅ Product catalog with variants
- ✅ Search and filtering
- ✅ Shopping cart
- ✅ User authentication (login/signup)
- ✅ Content-based recommendations
- ✅ Collaborative filtering
- ✅ Checkout flow
- ✅ Order confirmation

## 🛠 Tech Stack

- **Backend**: Flask, Flask-SQLAlchemy, Flask-Login
- **Frontend**: Bootstrap 5, JavaScript
- **ML**: scikit-learn, pandas, NumPy
- **Database**: SQLite
- **Deployment**: Docker, GitHub Actions

## 📊 Dataset

- 240 products
- 83 product families
- 8 store categories
- 6,000+ interaction records for recommendations

## 🔄 CI/CD Pipeline

GitHub Actions automatically:
- Tests on Python 3.9, 3.10, 3.11
- Runs code linting
- Builds Docker images
- Verifies app startup

**Status**: Check the [Actions tab](https://github.com/mattasaiswaroop5641-byte/E-commerce/actions) for pipeline status.

## 📦 Deployment Options

### Option 1: Docker (Recommended)
```bash
docker build -t ecommerce .
docker run -p 5000:5000 ecommerce
```

### Option 2: Railway.app
1. Connect your GitHub repo to Railway
2. Auto-deploys on each push
3. [Railway.app](https://railway.app)

### Option 3: Render
1. Create account at [render.com](https://render.com)
2. Connect GitHub repository
3. Set startup command: `gunicorn app:app`

### Option 4: Heroku
```bash
heroku create your-app-name
git push heroku main
```

## 📂 Project Structure

```
ecommerce/
├── app.py                 # Main Flask app
├── models.py             # Database models
├── forms.py              # WTForms
├── requirements.txt      # Dependencies
├── static/               # CSS, JS, images
│   ├── css/style.css
│   └── js/script.js
├── templates/            # HTML templates
└── recommenders/         # ML modules
    ├── content_based.py
    └── collab.py
```

## 🔐 Environment Variables

Create a `.env` file:
```
FLASK_ENV=development
FLASK_APP=app.py
SECRET_KEY=your-secret-key-here
```

## 📝 License

MIT License - Feel free to use this project!

## 👨‍💻 Author

[mattasaiswaroop5641-byte](https://github.com/mattasaiswaroop5641-byte)

---

**Get Started**: Clone the repo and run `python ecommerce/app.py`
