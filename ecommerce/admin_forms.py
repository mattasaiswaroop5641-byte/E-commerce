from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, IntegerField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional as OptionalValidator


class AdminLoginForm(FlaskForm):
    email = StringField("Admin Email", validators=[DataRequired(), Email(check_deliverability=False)])
    password = PasswordField("Password", validators=[DataRequired()])
    totp_code = StringField("Authenticator Code", validators=[OptionalValidator(), Length(min=6, max=10)])
    remember = BooleanField("Remember this device (30 days)")
    submit = SubmitField("Sign in")


class AdminOrderStatusForm(FlaskForm):
    status = SelectField(
        "Order Status",
        choices=[
            ("pending_payment", "Payment Pending"),
            ("confirmed", "Order Confirmed"),
            ("processing", "Processing"),
            ("shipped", "Shipped"),
            ("out_for_delivery", "Out for Delivery"),
            ("delivered", "Delivered"),
        ],
        validators=[DataRequired()],
    )
    note = TextAreaField("Internal Note", validators=[OptionalValidator(), Length(max=500)])
    submit = SubmitField("Update order")


class AdminTicketUpdateForm(FlaskForm):
    status = SelectField(
        "Ticket Status",
        choices=[("open", "Open"), ("investigating", "Investigating"), ("resolved", "Resolved"), ("closed", "Closed")],
        validators=[DataRequired()],
    )
    note = TextAreaField("Internal Note", validators=[OptionalValidator(), Length(max=500)])
    submit = SubmitField("Update ticket")


class AdminDiscountForm(FlaskForm):
    family_id = StringField("Family ID", validators=[DataRequired(), Length(min=2, max=120)])
    percent_off = IntegerField("Discount %", validators=[DataRequired(), NumberRange(min=0, max=90)])
    active = BooleanField("Active", default=True)
    submit = SubmitField("Save discount")


class AdminProductForm(FlaskForm):
    name = StringField("Product Name", validators=[DataRequired(), Length(min=2, max=220)])
    product_family_id = StringField("Family ID", validators=[DataRequired(), Length(min=2, max=140)])
    category = StringField("Category", validators=[DataRequired(), Length(min=2, max=120)])
    subcategory = StringField("Subcategory", validators=[OptionalValidator(), Length(max=120)])
    brand = StringField("Brand", validators=[OptionalValidator(), Length(max=120)])
    description = TextAreaField("Description", validators=[OptionalValidator(), Length(max=2000)])
    price = DecimalField("Price", places=2, rounding=None, validators=[DataRequired(), NumberRange(min=0, max=1_000_000)])
    image_url = StringField("Image URL", validators=[OptionalValidator(), Length(max=2000)])
    variant_label = StringField("Variant Label", validators=[OptionalValidator(), Length(max=120)])
    is_default = BooleanField("Default variant", default=True)
    active = BooleanField("Active", default=True)
    submit = SubmitField("Save product")
