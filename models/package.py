from .base import db, BaseModel

class Package(BaseModel):
    __tablename__ = "package"

    package_id = db.Column(db.Integer, primary_key=True, index=True, autoincrement=True)
    package_reg_ref = db.Column(db.String)
    package_pack = db.Column(db.String)
    package_price = db.Column(db.String)
    package_status = db.Column(db.String)