from .base import db, BaseModel

class DrugCompany(BaseModel):
    __tablename__ = "drug_company"

    drug_company_id = db.Column(db.Integer, primary_key=True, index=True, autoincrement=True)
    drug_company_reg_no = db.Column(db.String)
    drug_company_company_name = db.Column(db.String)
    drug_company_country = db.Column(db.String)
    drug_company_type = db.Column(db.String)
