from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional as OptionalValidator

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class SignupForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=150)])
    # Do not require DNS deliverability checks at form-validation time.
    email = StringField('Email', validators=[DataRequired(), Email(check_deliverability=False)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

class UserProfileForm(FlaskForm):
    username = StringField('Name', validators=[DataRequired(), Length(min=2, max=150)])
    email = StringField('Email', validators=[DataRequired(), Email(check_deliverability=False)])
    phone = StringField('Phone', validators=[OptionalValidator(), Length(max=40)])
    profile_pic_url = StringField('Profile Picture URL', validators=[OptionalValidator(), Length(max=500)])
    submit = SubmitField('Update Profile')

class OTPForm(FlaskForm):
    otp = StringField('Enter 6-digit OTP', validators=[DataRequired(), Length(min=6, max=6)])
    submit = SubmitField('Verify')
