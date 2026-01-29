from .base import db, BaseModel

class DrugPrice(BaseModel):
    __tablename__ = "drug_price"

    drug_company_id = db.Column(db.Integer, primary_key=True, index=True, autoincrement=True)
    drug_price_reg_no = db.Column(db.Integer)
    drug_pack = db.Column(db.String)
    drug_price = db.Column(db.String)
