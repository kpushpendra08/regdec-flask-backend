from .base import db, BaseModel

class ActiveIngredient(BaseModel):
    __tablename__ = 'active_ingredient'

    id = db.Column(db.Integer, primary_key=True)
    activeingredient_id = db.Column(db.String(100), nullable=True)
    activeingredient_name = db.Column(db.Text)
    activeingredient_class = db.Column(db.Text, nullable=True)