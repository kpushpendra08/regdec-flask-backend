from .base import db, BaseModel

class Decree(BaseModel):
    __tablename__ = 'decree'

    decree_id = db.Column(db.Integer, primary_key=True)
    decree_year = db.Column(db.Integer)
    decree_decreenumber = db.Column(db.Integer)
    decree_typeofcommittee = db.Column(db.String(255))
    decree_active_ingredient = db.Column(db.Text)
    decree_decision = db.Column(db.Text)
    decree_standarized_decision = db.Column(db.Text)
    decree_reason_of_decision = db.Column(db.Text)
    decree_summary_of_decision = db.Column(db.Text)
    decree_category = db.Column(db.String(255))
    decree_pageno = db.Column(db.Integer)
    decree_link = db.Column(db.String(500))
    decree_name_for_the_link = db.Column(db.String(255))
    decree_country = db.Column(db.String(100))

    technical_committee_dates = db.relationship(
        'DecreeTechnicalCommitteeDate',
        back_populates='decree',
        cascade='all, delete-orphan',
        lazy=True
    )

    session_dates = db.relationship(
        'DecreeSessionDate',
        back_populates='decree',
        cascade='all, delete-orphan',
        lazy=True
    )
