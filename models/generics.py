from .base import db, BaseModel

class Generics(BaseModel):
    __tablename__ = "generics"

    generics_id = db.Column(db.Integer, primary_key=True, index=True, autoincrement=True)
    generics_reg_no = db.Column(db.Integer)
    generics_name = db.Column(db.String)
