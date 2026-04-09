# ShadowMarket

A Flask ecommerce showcase with a richer catalog, grouped variants, cart and checkout flow, and hybrid recommendations.

## What Is Included

- Variant-aware catalog with grouped family cards
- Search, category browsing, product detail, cart, checkout, and order confirmation
- Login and signup with SQLite
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
