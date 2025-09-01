from .base import db, BaseModel

class Company(BaseModel):
    __tablename__ = 'company'

    company_id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(255), nullable=False)
    company_contactperson = db.Column(db.String(255))
    company_email = db.Column(db.String(255))
    company_contact = db.Column(db.String(20))
    company_address = db.Column(db.Text)
    company_country = db.Column(db.String(100))
    company_license_status = db.Column(db.String(100))
    company_active = db.Column(db.Boolean, default=True)
