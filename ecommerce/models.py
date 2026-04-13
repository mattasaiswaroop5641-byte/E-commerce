from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

class Interaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, default=1)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

    user = db.relationship('User', backref=db.backref('interactions', lazy=True))


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    tracking_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    customer_name = db.Column(db.String(150), nullable=False)
    customer_email = db.Column(db.String(150), nullable=False, index=True)
    customer_phone = db.Column(db.String(40), nullable=False)
    customer_address = db.Column(db.String(255), nullable=False)
    customer_city = db.Column(db.String(80), nullable=False)
    customer_postal_code = db.Column(db.String(30), nullable=False)
    payment_method_id = db.Column(db.String(40), nullable=False)
    payment_method_label = db.Column(db.String(120), nullable=False)
    payment_status = db.Column(db.String(120), nullable=False)
    payment_gateway = db.Column(db.String(40), nullable=False, default="manual")
    payment_reference = db.Column(db.String(160), nullable=False, default="")
    status = db.Column(db.String(40), nullable=False, default="processing", index=True)
    eta = db.Column(db.String(80), nullable=False)
    placed_at_display = db.Column(db.String(80), nullable=False)
    items_json = db.Column(db.JSON, nullable=False)
    summary_json = db.Column(db.JSON, nullable=False)
    confirmation_email_sent = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    user = db.relationship('User', backref=db.backref('orders', lazy=True))


class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    order_id = db.Column(db.String(40), nullable=False, default="", index=True)
    tracking_number = db.Column(db.String(40), nullable=False, default="")
    customer_name = db.Column(db.String(150), nullable=False)
    customer_email = db.Column(db.String(150), nullable=False, index=True)
    subject = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(40), nullable=False, default="open", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    user = db.relationship('User', backref=db.backref('support_tickets', lazy=True))
