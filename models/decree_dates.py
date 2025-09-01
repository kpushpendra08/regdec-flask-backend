from .base import db, BaseModel

class DecreeTechnicalCommitteeDate(BaseModel):
    __tablename__ = 'decree_technical_committee_date'

    id = db.Column(db.Integer, primary_key=True)
    decree_id = db.Column(db.Integer, db.ForeignKey('decree.decree_id'), nullable=False)
    date = db.Column(db.Date)

    decree = db.relationship('Decree', back_populates='technical_committee_dates')

class DecreeSessionDate(BaseModel):
    __tablename__ = 'decree_session_date'

    id = db.Column(db.Integer, primary_key=True)
    decree_id = db.Column(db.Integer, db.ForeignKey('decree.decree_id'), nullable=False)
    date = db.Column(db.Date)

    decree = db.relationship('Decree', back_populates='session_dates')
