from .base import db, BaseModel
import hashlib

def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

class User(BaseModel):
    __tablename__ = 'user'

    user_id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(255))
    user_email = db.Column(db.String(255), nullable=False, unique=True)
    user_password = db.Column(db.String(255))
    user_role = db.Column(db.String(255), default="user")
    user_contact = db.Column(db.String(20))
    user_company_id = db.Column(db.Integer, db.ForeignKey('company.company_id'))
    user_country = db.Column(db.String(100))
    user_licensestatus = db.Column(db.String(100))
    user_active = db.Column(db.Boolean, default=True)

    company = db.relationship('Company', backref=db.backref('users', lazy=True))

    def verify_password(self, password):
        return self.user_password == hash_password(password)
