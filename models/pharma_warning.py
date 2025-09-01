from .base import db, BaseModel


class PharmaWarning(BaseModel):
    __tablename__ = 'pharma_warning'

    pharma_warning_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    pharma_warning_no = db.Column(db.String(255))
    pharma_warning_decision_date = db.Column(db.Date)
    pharma_warning_date_of_update = db.Column(db.Date)
    pharma_warning_class = db.Column(db.String(255))
    pharma_warning_active_ingredient = db.Column(db.String(255))
    pharma_warning_dosage_form = db.Column(db.String(255))
    pharma_warning_route_of_administration = db.Column(db.String(255))
    pharma_warning_grace_period = db.Column(db.String(255))
    pharma_warning_compliance_deadline = db.Column(db.Date)
    pharma_warning_decision_type = db.Column(db.String(255))
    pharma_warning_purpose_of_decision = db.Column(db.String(255))
    pharma_warning_regulatory_reference = db.Column(db.String(255))
    pharma_warning_page_no = db.Column(db.String(255))
    pharma_warning_link = db.Column(db.String(1000))
