from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from typing import Optional, List, Any
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __allow_unmapped__ = True
    id: int = db.Column(db.Integer, primary_key=True)
    username: str = db.Column(db.String(150), unique=True, nullable=False)
    email: str = db.Column(db.String(150), unique=True, nullable=False)
    password_hash: str = db.Column(db.String(128), nullable=False)
    interactions: "List[Interaction]"
    orders: "List[Order]"
    support_tickets: "List[SupportTicket]"

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

class Interaction(db.Model):
    __allow_unmapped__ = True
    id: int = db.Column(db.Integer, primary_key=True)
    user_id: int = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id: int = db.Column(db.Integer, nullable=False)
    quantity: int = db.Column(db.Integer, default=1)
    timestamp: datetime = db.Column(db.DateTime, default=db.func.current_timestamp())

    user = db.relationship('User', backref=db.backref('interactions', lazy=True))


class Order(db.Model):
    __allow_unmapped__ = True
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    tracking_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    user_id: Optional[int] = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    customer_name: str = db.Column(db.String(150), nullable=False)
    customer_email: str = db.Column(db.String(150), nullable=False, index=True)
    customer_phone: str = db.Column(db.String(40), nullable=False)
    customer_address: str = db.Column(db.String(255), nullable=False)
    customer_city: str = db.Column(db.String(80), nullable=False)
    customer_postal_code: str = db.Column(db.String(30), nullable=False)
    payment_method_id: str = db.Column(db.String(40), nullable=False)
    payment_method_label: str = db.Column(db.String(120), nullable=False)
    payment_status: str = db.Column(db.String(120), nullable=False)
    payment_gateway: str = db.Column(db.String(40), nullable=False, default="manual")
    payment_reference: str = db.Column(db.String(160), nullable=False, default="")
    status: str = db.Column(db.String(40), nullable=False, default="processing", index=True)
    eta: str = db.Column(db.String(80), nullable=False)
    placed_at_display: str = db.Column(db.String(80), nullable=False)
    items_json: Any = db.Column(db.JSON, nullable=False)
    summary_json: Any = db.Column(db.JSON, nullable=False)
    confirmation_email_sent: bool = db.Column(db.Boolean, nullable=False, default=False)
    created_at: datetime = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    updated_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    user: Any = db.relationship('User', backref=db.backref('orders', lazy=True))


class SupportTicket(db.Model):
    __allow_unmapped__ = True
    id: int = db.Column(db.Integer, primary_key=True)
    ticket_id: str = db.Column(db.String(40), unique=True, nullable=False, index=True)
    user_id: Optional[int] = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    order_id: str = db.Column(db.String(40), nullable=False, default="", index=True)
    tracking_number: str = db.Column(db.String(40), nullable=False, default="")
    customer_name: str = db.Column(db.String(150), nullable=False)
    customer_email: str = db.Column(db.String(150), nullable=False, index=True)
    subject: str = db.Column(db.String(180), nullable=False)
    message: str = db.Column(db.Text, nullable=False)
    status: str = db.Column(db.String(40), nullable=False, default="open", index=True)
    created_at: datetime = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    updated_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    user: Any = db.relationship('User', backref=db.backref('support_tickets', lazy=True))


class DiscountRule(db.Model):
    __allow_unmapped__ = True
    id: int = db.Column(db.Integer, primary_key=True)
    family_id: str = db.Column(db.String(140), nullable=False, index=True, unique=True)
    percent_off: int = db.Column(db.Integer, nullable=False, default=0)
    active: bool = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at: datetime = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    updated_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )


class AdminAuditLog(db.Model):
    __allow_unmapped__ = True
    id: int = db.Column(db.Integer, primary_key=True)
    admin_email: str = db.Column(db.String(180), nullable=False, index=True)
    action: str = db.Column(db.String(180), nullable=False, index=True)
    target_type: str = db.Column(db.String(80), nullable=False, default="", index=True)
    target_id: str = db.Column(db.String(120), nullable=False, default="", index=True)
    detail: str = db.Column(db.Text, nullable=False, default="")
    ip_address: str = db.Column(db.String(80), nullable=False, default="")
    created_at: datetime = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())


class AdminProduct(db.Model):
    __allow_unmapped__ = True
    id: int = db.Column(db.Integer, primary_key=True)
    product_id: int = db.Column(db.Integer, nullable=False, unique=True, index=True)
    product_family_id: str = db.Column(db.String(140), nullable=False, index=True)
    name: str = db.Column(db.String(220), nullable=False)
    price: float = db.Column(db.Float, nullable=False, default=0.0)
    category: str = db.Column(db.String(120), nullable=False, default="Uncategorized", index=True)
    subcategory: str = db.Column(db.String(120), nullable=False, default="")
    brand: str = db.Column(db.String(120), nullable=False, default="")
    description: str = db.Column(db.Text, nullable=False, default="")
    variant_type: str = db.Column(db.String(120), nullable=False, default="")
    variant_value: str = db.Column(db.String(120), nullable=False, default="")
    variant_label: str = db.Column(db.String(120), nullable=False, default="")
    is_default: bool = db.Column(db.Boolean, nullable=False, default=True)
    image_url: str = db.Column(db.Text, nullable=False, default="")
    thumb_image_url: str = db.Column(db.Text, nullable=False, default="")
    hero_image_url: str = db.Column(db.Text, nullable=False, default="")
    active: bool = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at: datetime = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    updated_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
