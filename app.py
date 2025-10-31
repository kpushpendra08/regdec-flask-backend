from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
import sys
import hashlib
import json
import re
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from pathlib import Path
from functools import wraps
from init_app import create_app
from models import db, User, Decree, DecreeTechnicalCommitteeDate, \
    DecreeSessionDate, ActiveIngredient, PharmaWarning, Drugdata, \
    Generics, Package, DrugCompany, DrugPrice, Company
import jwt
app = create_app()

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
# Start with all data
engine = create_engine(app.config["SQLALCHEMY_DATABASE_URI"]) # Replace with your DB path

# Column names from your CSV
COLUMNS = {
    'ingredient': 'activeingredientdosageformstrength',
    'committee': 'typeofcommittee',
    'decision': 'decision',
    'standardDecision': 'standarizeddecision',
    'category': 'category',
    'reason': 'reasonofdecision',
    'date': 'Date of Session / Implementation of Decision',
    'year': 'year',
    'link': 'link',
    'page': 'pageno',
    'dateTechnicalCommittee': 'dateoftechnicalcommittee'
}

def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_password, provided_password):
    """Verify a stored password against provided password"""
    return stored_password == hash_password(provided_password)

BATCH_SIZE = 1000

def bulk_batch_insert(items, model):
    total_inserted = 0

    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        try:
            objects = [model(**item) for item in batch]
            db.session.bulk_save_objects(objects)
            db.session.commit()
            total_inserted += len(objects)
        except Exception as err:
            db.session.rollback()
            print(f"==== Error in batch {i//BATCH_SIZE + 1}: {err}")
            print("Example failing row:", batch[0])

    return {"status": "success", "inserted": total_inserted}

def login_required(f):
    """Decorator to require valid JWT token for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({'message': 'Missing token'}), 401

        try:
            # Assume format: "Bearer <token>" or just "<token>"
            token = auth_header.split(" ")[-1]

            # Decode token
            decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            decoded_user = decoded.get('user')
            # Optionally check expiration manually (jwt.decode does this if verify=True)
            exp = decoded_user.get('exp')
            if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
                return jsonify({'message': 'Token expired'}), 401

            # Set user info for downstream usage (optional)
            request.user = decoded_user

        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Invalid token'}), 401
        except Exception as err:
            print("=====errr", err)

        return f(*args, **kwargs)
    return decorated_function

def fix_date_string_todate(date_str):
    # List of expected date formats
    date_formats = [
        "%Y-%m-%d",         # e.g., 2023-08-30
        "%d/%m/%Y",         # e.g., 30/08/2023
        "%m/%d/%Y",         # e.g., 08/30/2023
        "%Y-%m-%d %H:%M:%S",# e.g., 2023-08-30 14:30:00
        "%d-%b-%Y",         # e.g., 30-Aug-2023
        "%b %d, %Y",        # e.g., Aug 30, 2023
        "%Y/%m/%d",         # e.g., 2023/08/30
        "%Y-%m-%dT%H:%M:%S",# e.g., 2023-08-30T14:30:00 (ISO 8601)
        "%d-%m-%Y"
    ]
    for date_format in date_formats:
        try:
            # Try parsing the date string with the current format
            return datetime.strptime(date_str, date_format)
        except ValueError:
            continue  # If parsing fails, try the next format
    
    # Return None if no format matched
    return None

def fix_date_string(date_str):
    parts = date_str.strip().split("-")
    if len(parts) > 1 and not str(parts[1]).isdigit():
        # Pad the year with zero(s) at the end
        if len(parts[1]) < 2:
            parts[1] = parts[1].rjust(2, '0')
        if len(parts[2]) < 4:
            parts[2] = parts[2].ljust(4, '0')
        return fix_date_string_todate("-".join(parts))
    elif len(parts) == 3 and len(parts[2]) < 4 and len(date_str) != 10:
        # Pad the year with zero(s) at the end
        parts[2] = parts[2].ljust(4, '0')
        return fix_date_string_todate("-".join(parts))
    
    return fix_date_string_todate(date_str)

def parse_dates_field(raw_value):  
    if isinstance(raw_value, list):
        result = []
        for item in raw_value:
            if isinstance(item, str):
                # Split by both ',' and ';'
                parts = [fix_date_string(d.strip()) for d in re.split(r'[,;\n\r]+', raw_value) if d.strip()]
                result.extend(parts)
            else:
                result.append(str(item).strip())
        return result

    elif isinstance(raw_value, str):
        parts = [fix_date_string(d.strip()) for d in re.split(r'[,;\n\r]+', raw_value) if d.strip()]
        return parts
    elif isinstance(raw_value, datetime):
        return [raw_value]

    return []  # fallback for None or unexpected types

def read_file_with_multiple_encodings(file_path, encodings=None):
    if encodings is None:
        encodings = ['utf-8', 'utf-8-sig', 'utf-16', 'cp1252', 'latin1']  # Most common fallback encodings

    for enc in encodings:
        try:
            df = pd.read_csv(file_path, encoding=enc)
            print(f"✅ File read successfully with encoding: {enc}")
            return df
        except UnicodeDecodeError:
            print(f"❌ Failed with encoding: {enc}")
        except Exception as e:
            print(f"❌ Other error with encoding {enc}: {e}")
    
    raise UnicodeDecodeError("All provided encodings failed.")

def truncate_table(model):
    # Delete all rows from the table
    db.session.query(model).delete()
    db.session.commit()


def uploadDecreeData(df):
    try:
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('.', '', regex=False)\
                                .str.replace('/', '', regex=False)\
                                .str.replace(' ', '', regex=False)\
                                .str.replace('\n', '', regex=False).str.lower()

        print(f"  Total records: {len(df)}")
        print(f"  Columns: {list(df.columns)}")

        truncate_table(Decree)
        truncate_table(DecreeTechnicalCommitteeDate)
        truncate_table(DecreeSessionDate)

        if len(df) == 0:
            return "No data to insert."

        df = df.fillna('')

        decree_data = []
        tech_committee_dates = []
        session_dates = []

        for idx, row in df.iterrows():
            decree_row = {
                "decree_year": row.get('year'),
                "decree_decreenumber": row.get('decreenumber'),
                "decree_typeofcommittee": row.get('typeofcommittee'),
                "decree_decision": row.get('decision'),
                "decree_active_ingredient": row.get('activeingredientdosageformstrength'),
                "decree_standarized_decision": row.get('standarizeddecision'),
                "decree_reason_of_decision": row.get('reasonofdecision'),
                "decree_summary_of_decision": row.get('summaryofdecision'),
                "decree_category": row.get('category'),
                "decree_pageno": row.get('pageno'),
                "decree_link": row.get('link'),
                "decree_name_for_the_link": row.get('nameforthelink'),
            }

            decree_data.append(decree_row)

        # Insert decrees using bulk insert
        inserted = bulk_batch_insert(decree_data, Decree)

        # Now fetch all decrees to get their IDs (assuming there's a unique constraint on decree number + year or similar)
        decrees = Decree.query.all()
        decree_lookup = {(d.decree_year, d.decree_decreenumber): d.decree_id for d in decrees}
        # print("======decree_lookup0", decree_lookup)
        # Prepare related date tables
        for idx, row in df.iterrows():
            key = (row.get('year'), row.get('decreenumber'))
            decree_id = decree_lookup.get(key)

            if not decree_id:
                print(f"Warning: No decree found for row {idx} with key {key}")
                continue

            technical_dates = parse_dates_field(row.get('dateoftechnicalcommittee'))
            # print("=======", row.get('dateoftechnicalcommittee'), technical_dates)
            for dt in technical_dates:
                tech_committee_dates.append({
                    "decree_id": decree_id,
                    "date": dt.date()
                })

            session_impl_dates = parse_dates_field(row.get('dateofsessionimplementationofdecision'))
            # print("=======",decree_id, row.get('session_impl_dates'), session_impl_dates)
            for dt in session_impl_dates:
                session_dates.append({
                    "decree_id": decree_id,
                    "date": dt.date()
                })

        # Bulk insert related dates
        bulk_batch_insert(tech_committee_dates, DecreeTechnicalCommitteeDate)
        bulk_batch_insert(session_dates, DecreeSessionDate)

        message = f"Inserted {inserted['inserted']} decrees with related dates."
        print("=====", message)
        return message

    except Exception as e:
        print("===err", e)
        error = f"Error reading file: {str(e)}"
        return error




def activeIngredient(df):
    try:
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('.', '', regex=False).str.replace('/', '', regex=False).str.replace(' ', '', regex=False).str.replace('\n', '', regex=False).str.lower()
        
        print(f"  Total records: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        truncate_table(ActiveIngredient)
        if len(df) > 0:
            try:
                df = df.fillna('')
                records = []
                for _, row in df.iterrows():
                    data = {
                        "activeingredient_id": row.get('id'),
                        "activeingredient_name":row.get('activeingredient'),
                        "activeingredient_class":row.get('class')
                    }
                    record = ActiveIngredient(**data)
                    records.append(record)
                db.session.add_all(records)
                db.session.commit()
                message = f"Inserted {len(records)} rows into database."
                print("=====", message)
                return message
            except Exception as e:
                db.session.rollback()
                message = f"Error: {e}"
                return message

    except Exception as e:
        print("===err", e)
        error = f"Error reading file: {str(e)}"
        return error

def pharmaWarning(df):
    try:
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('.', '', regex=False).str.replace('/', '', regex=False).str.replace(' ', '', regex=False).str.replace('\n', '', regex=False).str.lower()
        
        print(f"  Total records: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        truncate_table(PharmaWarning)
        if len(df) > 0:
            try:
                df = df.astype(str)
                df = df.replace({np.nan: None, pd.NaT: None})
                records = []
                

                # print(df)
                for _, row in df.iterrows():
                    data = {
                        "pharma_warning_no": row.get('id'),
                        "pharma_warning_decision_date": parse_dates_field(row.get('decisiondate'))[0],
                        "pharma_warning_date_of_update": parse_dates_field(row.get('dateofupdate(ifany)'))[0],
                        "pharma_warning_class": row.get('class'),
                        "pharma_warning_active_ingredient": row.get('activesubstance(genericname)'),
                        "pharma_warning_dosage_form": row.get('dosageform'),
                        "pharma_warning_route_of_administration": row.get('routeofadministration'),
                        "pharma_warning_grace_period": row.get('graceperiod'),
                        "pharma_warning_compliance_deadline": parse_dates_field(row.get('compliancedeadline'))[0],
                        "pharma_warning_decision_type": row.get('decisiontype'),
                        "pharma_warning_purpose_of_decision": row.get('purposeofdecision'),
                        "pharma_warning_regulatory_reference": row.get('regulatoryreference(s)'),
                        "pharma_warning_page_no": row.get('pageno'),
                        "pharma_warning_link": row.get('link'),
                    }
                    records.append(data)
                msg = bulk_batch_insert(records, PharmaWarning)    
                return "inserted"
            except Exception as e:
                db.session.rollback()
                print("=====", e)
                message = f"Error: {e}"
                return message

    except Exception as e:
        print("===err", e)
        error = f"Error reading file: {str(e)}"
        return error
    

def drugData(df):
    try:
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('.', '', regex=False).str.replace('/', '', regex=False).str.replace(' ', '', regex=False).str.replace('\n', '', regex=False).str.lower()
        
        print(f"  Total records: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        truncate_table(Drugdata)
        if len(df) > 0:
            try:
                # df = df.fillna('')
                df = df.replace({np.nan: None, pd.NaT: None})
                records = []
                # print(df)
                for _, row in df.iterrows():
                    data = {
                        "drugdata_reg_no": row.get('registrationnumber'),
                        "drugdata_active_ingredient": row.get('activeingredient'),
                        "drugdata_trade_name": row.get('tradename'),
                        "drugdata_product_type": row.get('producttype'),
                        "drugdata_dosage_form": row.get('dosageform'),
                        "drugdata_shelf_life": row.get('shelflife'),
                        "drugdata_route": row.get('route'),
                        "drugdata_strength": row.get('strength'),
                        "drugdata_pack_unit": row.get('packunit'),
                        "drugdata_approved_packs": row.get('approvedpacks'),
                        "drugdata_applicant": row.get('applicant'),
                        "drugdata_registration_no": row.get('registrationnumber'),
                        "drugdata_registration_type": row.get('registrationtype'),
                        "drugdata_marketing_type": row.get('marketingtype'),
                        "drugdata_marketing_status": row.get('marketingstatus'),
                        "drugdata_license_status": row.get('licensestatus'),
                        "drugdata_price_status": row.get('pricestatus'),
                        "drugdata_physical_characters": row.get('physicalcharcaters'),
                        "drugdata_storage_conditions": row.get('storageconditions'),
                        "drugdata_registration_data": row.get('registrationdata'),
                        "drugdata_combo_pack": row.get('combopack'),
                        "drugdata_reference": row.get('reference'),
                        "drugdata_leaflet": row.get('leaflet'),
                        "drugdata_comments": row.get('comments'),
                        "drugdata_page_number": row.get('page_number'),
                        "drugdata_row_number": row.get('row_number'),
                    }
                    # record = Drugdata(**data)
                    records.append(data)
                    # try:
                    #     db.session.add(record)
                    #     db.session.commit()
                    #     # successful += 1
                    # except IntegrityError as ie:
                    #     db.session.rollback()
                    #     # failed += 1
                    #     print(f"[SKIPPED] Duplicate or integrity error for: {data} -> {ie.orig}")
                    # except Exception as e:
                    #     print("=====", e)
                    #     db.session.rollback()
                    #     # failed += 1
                    #     print(f"[ERROR] Failed to insert: {data} -> {str(e)}")
                msg = bulk_batch_insert(records, Drugdata)    
                return "inserted"
                # db.session.add_all(records)
                # db.session.commit()
                # message = f"Inserted {len(records)} rows into database."
                # print("=====", message)
                # return message
            except Exception as e:
                db.session.rollback()
                print("=====", e)
                message = f"Error: {e}"
                return message

    except Exception as e:
        print("===err", e)
        error = f"Error reading file: {str(e)}"
        return error
    

def generics(df):
    try:
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('.', '', regex=False).str.replace('/', '', regex=False).str.replace(' ', '', regex=False).str.replace('\n', '', regex=False).str.lower()
        
        print(f"  Total records: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        truncate_table(Generics)
        if len(df) > 0:
            try:
                df = df.replace({np.nan: None, pd.NaT: None})
                records = []
                for _, row in df.iterrows():
                    data = {
                        "generics_reg_no": row.get('registrationnumber'),
                        "generics_name": row.get('genericname'),                        
                    }
                    records.append(data)
                msg = bulk_batch_insert(records, Generics)    
                return "inserted"
            except Exception as e:
                db.rollback()
                print("=====", e)
                message = f"Error: {e}"
                return message

    except Exception as e:
        print("===err", e)
        error = f"Error reading file: {str(e)}"
        return error

def packages(df):
    try:
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('.', '', regex=False).str.replace('/', '', regex=False).str.replace(' ', '', regex=False).str.replace('\n', '', regex=False).str.lower()
        
        print(f"  Total records: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        truncate_table(Package)
        if len(df) > 0:
            try:
                df = df.replace({np.nan: None, pd.NaT: None})
                records = []
                for _, row in df.iterrows():
                    data = {
                        "package_reg_ref": row.get('registrationnumber'),
                        "package_pack": row.get('pack'),
                        "package_price": row.get('price'),                        
                    }
                    records.append(data)
                msg = bulk_batch_insert(records, Package)    
                return "inserted"
            except Exception as e:
                db.rollback()
                print("=====", e)
                message = f"Error: {e}"
                return message

    except Exception as e:
        print("===err", e)
        error = f"Error reading file: {str(e)}"
        return error    


def drugcompany(df):
    try:
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('.', '', regex=False).str.replace('/', '', regex=False).str.replace(' ', '', regex=False).str.replace('\n', '', regex=False).str.lower()
        
        print(f"  Total records: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        truncate_table(DrugCompany)
        if len(df) > 0:
            try:
                df = df.replace({np.nan: None, pd.NaT: None})
                records = []
                for _, row in df.iterrows():
                    data = {
                        "drug_company_reg_no": row.get('registrationnumber'),
                        "drug_company_company_name": row.get('companyname'),
                        "drug_company_country": row.get('country'), 
                        "drug_company_type": row.get('type'),                        
                    }
                    records.append(data)
                msg = bulk_batch_insert(records, DrugCompany)    
                return "inserted"
            except Exception as e:
                db.rollback()
                print("=====", e)
                message = f"Error: {e}"
                return message

    except Exception as e:
        print("===err", e)
        error = f"Error reading file: {str(e)}"
        return error
    
def drugprice(df):
    try:
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('.', '', regex=False).str.replace('/', '', regex=False).str.replace(' ', '', regex=False).str.replace('\n', '', regex=False).str.lower()
        
        print(f"  Total records: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        truncate_table(DrugPrice)
        if len(df) > 0:
            try:
                df = df.replace({np.nan: None, pd.NaT: None})
                records = []
                for _, row in df.iterrows():
                    data = {
                        "drug_price_reg_no": row.get('registrationnumber'),
                        "drug_pack": row.get('pack'),
                        "drug_price": row.get('price')                        
                    }
                    records.append(data)
                msg = bulk_batch_insert(records, DrugPrice)    
                return "inserted"
            except Exception as e:
                db.rollback()
                print("=====", e)
                message = f"Error: {e}"
                return message

    except Exception as e:
        print("===err", e)
        error = f"Error reading file: {str(e)}"
        return error
    
@app.route('/api/v1/upload', methods=['POST'])
def upload():
    file = request.files['file']
    filename = secure_filename(file.filename)
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)
    file_type = request.form.get('file_type')
    print("=====file_type", file_type)
    result = {}
    if filename.endswith('.csv'):
        df = read_file_with_multiple_encodings(path)
        result[file_type] = df
    elif filename.endswith('.xlsx'):
        dfs = pd.read_excel(file, sheet_name=None)
        print("====dfs", len(dfs))
        for sheet_name, df in dfs.items():
            print("===sheetname", sheet_name)
            if len(dfs) == 1:
                result[file_type] = df
            else:
                result[sheet_name] = df
            # result[sheet_name] = df.head().to_dict()  # just show first few rows per sheet
    else:
        return jsonify({"success": False, "message": "Unsupported file format."}), 401
    msg = ""    
    if file_type == "decree":
        msg = uploadDecreeData(df)
    elif file_type == "activeingredient":
        msg = activeIngredient(df)
    elif file_type == "drugdata":
        msg = drugData(df)
    elif file_type == "pharmawarning":
        msg = pharmaWarning(df)
    elif file_type == "generics":
        msg = generics(df)
    elif file_type == "package":
        msg = packages(df)
    elif file_type == "drugcompany":
        msg = drugcompany(df)
    elif file_type == "drugprice":
        msg = drugcompany(df)
    elif file_type == "all":
        pass
    return jsonify({"success": True, "message": msg}), 200


def addBulkUserData(df):
    try:
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('.', '', regex=False).str.replace('/', '', regex=False).str.replace(' ', '', regex=False).str.replace('\n', '', regex=False).str.replace("'", '', regex=False).str.lower()
        
        print(f"  Total records: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        if len(df) > 0:
            try:
                df = df.replace({np.nan: None, pd.NaT: None})
                records = []
                for index, row in df.iterrows():
                    print(index)
                    try:
                        data = {
                            "user_name": row.get('whatsyourname?'),
                            "user_email": row.get('whatsyouremailaddress?'),
                            "user_password": hash_password("Regdec@2025"),
                            "meta_data": {
                                "submissionid": row.get('submissionid'),
                                "respondentid": row.get('respondentid'),
                                # "submittedat": row.get('submittedat'),
                                "user_contact": row.get('whatsappnumber(optional)'),
                                "jobtitlerole": row.get('jobtitlerole'),
                                "linkedinprofile": row.get('linkedinprofile'),
                                "areaofinterestinregdec": row.get('areaofinterestinregdec'),
                                "willyouattendpharmaconex2025?": row.get('willyouattendpharmaconex2025?'),
                                "wedlovetohearfromyou—anyfeedback,ideas,ornotesaremorethanwelcome": row.get('we’dlovetohearfromyou—anyfeedback,ideas,ornotesaremorethanwelcome💬'),
                                "email": row.get('email'),
                                "linkedin": row.get('linkedin'),
                                "whatsapp": row.get('whatsapp'),
                                "notesfromhisexperience": row.get('notesfromhisexperience')
                            }                      
                        }
                        records.append(data)
                        user = User(**data)
                        db.session.add(user)
                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        print("=====", e)  
                return "inserted"
            except Exception as e:
                db.session.rollback()
                print("=====", e)
                message = f"Error: {e}"
                return message

    except Exception as e:
        print("===err", e)
        error = f"Error reading file: {str(e)}"
        return error

@app.route('/api/v1/addbulkuser', methods=['POST'])
def addBulkUser():
    file = request.files['file']
    filename = secure_filename(file.filename)
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)
    result = {}
    if filename.endswith('.csv'):
        df = read_file_with_multiple_encodings(path)
    elif filename.endswith('.xlsx'):
        dfs = pd.read_excel(file, sheet_name=None)
        print("====dfs", len(dfs))
        for sheet_name, df in dfs.items():
            print("===sheetname", sheet_name)
            addBulkUserData(df)
            # result[sheet_name] = df.head().to_dict()  # just show first few rows per sheet
    else:
        return jsonify({"success": False, "message": "Unsupported file format."}), 401
    
    return jsonify({"success": True, "message": "msg"}), 200

# Authentication routes
@app.route('/api/v1/login', methods=['POST'])
def login():
    """Login page"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({"success": False, "message": "Username and password required"}), 400

    # Query user by username
    user = User.query.filter_by(user_email=username).first()

    if user and user.verify_password(password):
        data = {
            "username": username,
            "user_email": user.user_email,
            "user_role": user.user_role
        }
        token = jwt.encode(
        {
            'user': data,
            'exp': datetime.utcnow() + timedelta(hours=2)
        },
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )
        return jsonify({"success": True, "message": "Login successful", "token": token, "user": data}), 200
    else:
        return jsonify({"success": False, "message": "Invalid username or password"}), 401
    
@app.route('/api/v1/change-password', methods=['POST'])
def change_password():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'message': 'Missing token'}), 401

    try:
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        decoded_user = decoded['user']
        user = User.query.filter_by(user_email=decoded_user['username']).first()

        if not user:
            return jsonify({'message': 'User not found'}), 404

        data = request.get_json()
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if not user.verify_password(current_password):
            return jsonify({'message': 'Incorrect current password'}), 401

        if new_password != confirm_password:
            return jsonify({'message': 'New passwords do not match'}), 400

        user.user_password = hash_password(new_password)
        db.session.commit()

        return jsonify({'message': 'Password updated successfully'}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Token expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token'}), 401


@app.route('/api/v1/users', methods=['GET'])
def get_all_users():
    """Get all users (admin only)"""
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'message': 'Missing token'}), 401

    try:
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        decoded_user = decoded['user']
        
        # Check if user is admin
        if decoded_user.get('user_role') != 'admin':
            return jsonify({'message': 'Unauthorized. Admin access required'}), 403

        # Get all users except admins
        users = User.query.filter(User.user_role != 'admin').all()
        user_list = [
            {
                'user_id': user.user_id,
                'user_email': user.user_email,
                'user_name': user.user_name,
                'user_role': user.user_role,
                'user_active': user.user_active
            }
            for user in users
        ]

        return jsonify({'success': True, 'users': user_list}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Token expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token'}), 401

@app.route('/api/v1/reset-user-password', methods=['POST'])
def reset_user_password():
    """Reset a user's password (admin only)"""
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'message': 'Missing token'}), 401

    try:
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        decoded_user = decoded['user']
        
        # Check if user is admin
        if decoded_user.get('user_role') != 'admin':
            return jsonify({'message': 'Unauthorized. Admin access required'}), 403

        data = request.get_json()
        user_email = data.get('user_email')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if not user_email or not new_password or not confirm_password:
            return jsonify({'message': 'All fields are required'}), 400

        if new_password != confirm_password:
            return jsonify({'message': 'Passwords do not match'}), 400

        # Find the user to reset password for
        user = User.query.filter_by(user_email=user_email).first()
        if not user:
            return jsonify({'message': 'User not found'}), 404

        # Prevent resetting admin passwords
        if user.user_role == 'admin':
            return jsonify({'message': 'Cannot reset admin user passwords'}), 403

        # Update the password
        user.user_password = hash_password(new_password)
        db.session.commit()

        return jsonify({'message': f'Password reset successfully for {user_email}'}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Token expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token'}), 401

@app.route('/api/v1/logout')
def logout():
    """Logout and clear session"""
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/api/v1/register', methods=['POST'])
def register():
    """Register a new user"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    email = data.get('email', '').strip()
    
    if not username or not password or not email:
        return jsonify({'success': False, 'message': 'All fields are required'}), 400
    

    if User.query.filter_by(user_name=username).first():
        return jsonify({"success": False, "message": "Username already exists"}), 409
    
    if User.query.filter_by(user_email=email).first():
        return jsonify({"success": False, "message": "Email already exists"}), 409

    # Optional user fields
    name = data.get('name', '').strip()
    job_title = data.get('jobTitle', '').strip()
    linkedin = data.get('linkedin', '').strip()
    country = data.get('country', '').strip()
    interest = data.get('interest', '').strip()
    attend = data.get('attend', False)
    whatsapp = data.get('whatsapp', '').strip()
    feedback = data.get('feedback', '').strip()

    # Handle company info if provided
    company_data = data.get('company')
    company_id = None
    if company_data:
        company_name = company_data.get('name', '').strip()
        company_location = company_data.get('location', '').strip()
        if company_name:  # Only create company if name is provided
            company = Company(
                company_name=company_name,
                company_address=company_location
            )
            db.session.add(company)
            db.session.commit()  # Commit to get the company_id
            company_id = company.company_id

    try:
        # Create new user instance
        user = User(
            user_name=username,
            user_email=email,
            user_password=hash_password(password),
            user_role="user",
            user_country=country,
            user_company_id=company_id,
            user_contact=whatsapp,
            meta_data= {
                "user_contact": whatsapp,
                "jobtitlerole": job_title,
                "linkedinprofile": linkedin,
                "areaofinterestinregdec": interest,
                "willyouattendpharmaconex2025?": attend,
                "wedlovetohearfromyou—anyfeedback,ideas,ornotesaremorethanwelcome": feedback
            }
        )
        db.session.add(user)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Registration successful'})
    except IntegrityError as e:
        db.session.rollback()
        # Check if it's a duplicate email error
        if 'user_email' in str(e.orig):
            return jsonify({'success': False, 'message': 'Email already exists'}), 409
        else:
            return jsonify({'success': False, 'message': 'Registration failed. Please try again.'}), 400
    except Exception as e:
        db.session.rollback()
        print(f"Registration error: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred during registration'}), 500

@app.route('/api/v1/user')
@login_required
def get_user():
    """Get current user info"""
    return jsonify({
        'username': session.get('user_id'),
        'email': session.get('user_email'),
        'role': session.get('user_role')
    })


@app.route('/api/v1/committees')
@login_required
def get_committees():
    """Get unique committees"""
    committees = [
            "Bioequivalence Committee", "Central Administration of Biological and Innovative Products and Clinical Studies", "Committee for Naming and Labeling", "Committee for Nephrology and Urology", "Committee for Pharmaceutical Inspection", "Committee for Rheumatology, Rehabilitation, and Orthopedic Surgery", "Drug Economics Committee", "Higher Inspection Committee", "Joint Committee (Pharmacovigilance and Invited Members)", "Joint Specialized Scientific Committee for Cancer and Radiopharmaceuticals", "Joint Specialized Scientific Committee for Dermatology and Andrology", "Joint Specialized Scientific Committee for General Surgery", "Joint Specialized Scientific Committee for Respiratory Diseases", 
            "Joint Specialized Scientific Committee for Urology and Nephrology", 
            "Joint Specialized Scientific Committee for Veterinary Drugs and Feed Additives", 
            "Joint Specialized Scientific Committee for Veterinary Medicines and Animal Feed Additives", "Joint Specialized Scientific Committee of Cardiology and Vascular Diseases and Vascular Diseases", "Joint Specialized Scientific Committee of Endocrinology and Metabolism", "Joint Specialized Scientific Committee of Gastroenterology and Hepatology", "Joint Specialized Scientific Committee of Internal Medicine", "Joint Specialized Scientific Committee of Psychiatry and Neurology", "Joint Specialized Scientific Committee of Rheumatology, Rehabilitation and Orthopedic Surgery", "Non-Reference Drugs Committee", "Pharmaceutical Registration", "Pharmacology Committee", "Pharmacovigilance Committee", "Quality Assessment Committee", "Rheumatology, Rehabilitation, and Orthopedic Surgery Committee", "Scientific Committee for Anesthesia", "Scientific Committee for Cancer and Radioactive Isotopes ", "Scientific Committee for Cardiovascular", "Scientific Committee for Dental Diseases and Surgery", "Scientific Committee for Dermatological Diseases", "Scientific Committee for Dermatological, Reproductive, and Urological Diseases", "Scientific Committee for Dermatology and Andrology", "Scientific Committee for Dermatology and Venereal Diseases", "Scientific Committee for Dermatology and Venereology", "Scientific Committee for Dermatology, Urology and Andrology", "Scientific Committee for Dermatology, Venereology, and Andrology", "Scientific Committee for Digestive System and Liver Diseases", "Scientific Committee for Ear, Nose, and Throat Diseases", "Scientific Committee for Endocrine Diseases", "Scientific Committee for Endocrinology", "Scientific Committee for Endocrinology and Diabetes ", "Scientific Committee for Endocrinology and Metabolism", "Scientific Committee for Eye and Retinal Diseases", "Scientific Committee for Eye Diseases", "Scientific Committee for Eye Diseases and Retinal Surgery", "Scientific Committee for Food Supplements ", "Scientific Committee for Gastrointestinal and Hepatic Diseases", "Scientific Committee for General Internal Medicine", "Scientific Committee for General Surgery", "Scientific Committee for Hematology", "Scientific Committee for Hepatology and Gastroenterology", "Scientific Committee for Internal Diseases", "Scientific Committee for Kidney and Urology Diseases", "Scientific Committee for Kidney Diseases", "Scientific Committee for Liver and Digestive Diseases", "Scientific Committee for Liver and Gastroenterology Diseases ", "Scientific Committee for Liver and Gastrointestinal Diseases ", "Scientific Committee for Medicinal Foods", "Scientific Committee for Nephrology and Urology", "Scientific Committee for Neurological and Mental Diseases", "Scientific Committee for Neurological and Psychiatric Diseases", "Scientific Committee for Neurological Diseases", "Scientific Committee for Neurological Disorders ", "Scientific Committee for Neurology and Psychiatry", "Scientific Committee for Obstetrics and Gynecology", "Scientific Committee for Obstetrics and Gynecology Diseases ", "Scientific Committee for Ocular Diseases and Retinal Surgery", "Scientific Committee for Ophthalmic Diseases and Retinal Surgery ", "Scientific Committee for Ophthalmic Diseases and Surgery ", "Scientific Committee for Ophthalmology", "Scientific Committee for Ophthalmology and Eye Diseases", "Scientific Committee for Ophthalmology and Retinal Diseases", "Scientific Committee for Pediatrics", "Scientific Committee for Psychiatric and Neurological Diseases", "Scientific Committee for Psychiatry and Neurology", "Scientific Committee for Respiratory Diseases", "Scientific Committee for Respiratory Diseases ", "Scientific Committee for Urology and Nephrology ", "Scientific Committee for Vaccines, Biologics, and Blood Derivatives", "Scientific Committee for Vaccines, Biologics, and Blood Products", "Scientific Committee for Veterinary Drugs and Feed Additives", "Scientific Committee for Veterinary Medicines and Animal Feed Additives", "Scientific Committee for Veterinary Medicines and Feed Additives", "Scientific Committee for Women's Diseases ", "Scientific Committee in Chest Diseases", "Scientific Committee in Dermatology", "Scientific Committee in Internal Medicine", "Scientific Committee in Veterinary Medicines and Feed Additives", "Scientific Committee Liver and Digestive Diseases ", "Scientific Committee of Anesthesia", "Scientific Committee of Anesthesia and Pain Management", "Scientific Committee of Anesthesia and Pain Management and Addiction Treatment", "Scientific Committee of Cancer and Radiology", "Scientific Committee of Cardiology and Vascular Diseases", "Scientific Committee of Cardiology and Vascular Diseases and Blood Vessels", "Scientific Committee of Cardiovascular and Vascular Diseases", "Scientific Committee of Chest Diseases", "Scientific Committee of Dentistry and Oral Surgery", "Scientific Committee of Dermatological, Genitourinary, and Urological Diseases", "Scientific Committee of Dermatological, Reproductive and Male Diseases", "Scientific Committee of Dermatology and Venereology", "Scientific Committee of Dermatology, Venereology and Andrology", "Scientific Committee of Dermatology , Venereology and Urology", "Scientific Committee of Dietary Supplements", "Scientific Committee of Disinfectants and Antiseptics", "Scientific Committee of Ear, Nose, and Throat", "Scientific Committee of Ear, Nose, and Throat Diseases", "Scientific Committee of Endocrine and Metabolic Diseases", "Scientific Committee of Endocrinology", "Scientific Committee of Endocrinology and Metabolism", "Scientific Committee of Endocrinology and Metabolism Diseases", "Scientific Committee of Gastroenterology", "Scientific Committee of Gastroenterology and Hepatology", "Scientific Committee of Gastrointestinal and Hepatology", "Scientific Committee of Gastrointestinal Diseases ", "Scientific Committee of General Surgery", "Scientific Committee of Heart Diseases", "Scientific Committee of Hematology", "Scientific Committee of Hepatology", "Scientific Committee of Internal Diseases", "Scientific Committee of Internal Medicine", "Scientific Committee of Kidney and Urinary Tract Diseases", "Scientific Committee of Liver and Gastrointestinal Diseases", "Scientific Committee of Liver Diseases ", "Scientific Committee of Medical Nutrition", "Scientific Committee of Mental and Neurological Diseases", "Scientific Committee of Nephrology and Urology", "Scientific Committee of Neurology and Psychiatry ", "Scientific Committee of Non-Reference Drugs ", "Scientific Committee of Obstetrics and Gynecology", "Scientific Committee of Oncology", "Scientific Committee of Oncology and Radioactive Isotopes", "Scientific Committee of Oncology and Radiology ", "Scientific Committee of Ophthalmic Diseases ", "Scientific Committee of Ophthalmology", "Scientific Committee of Ophthalmology and Eye Surgery", "Scientific Committee of Ophthalmology and Retinal Surgery", "Scientific Committee of Pain and Anesthesia ", "Scientific Committee of Pediatrics", "Scientific Committee of Psychiatry and Neurology", "Scientific Committee of Psychopharmacology and Neurology", "Scientific Committee of Pulmonology", "Scientific Committee of Pulmonology (Respiratory Diseases)", "Scientific Committee of Respiratory Diseases", "Scientific Committee of Rheumatic Diseases, Rehabilitation, and Orthopedic Surgery", "Scientific Committee of Rheumatology", "Scientific Committee of Rheumatology and Orthopedic Surgery", "Scientific Committee of Rheumatology and Rehabilitation ", "Scientific Committee of Rheumatology Diseases", "Scientific Committee of Rheumatology, Rehabilitation and Orthopedic Surgery", "Scientific Committee of the Internal Medicine", "Scientific Committee of Urology and Nephrology", "Scientific Committee of Veterinary Drugs and Feed Additives", "Scientific Committee of Veterinary Drugs", "Scientific Committee of Veterinary Medicines and Feed Additives", "Specialized Scientific Committee for Dermatology, Venereology, and Andrology ", "Specialized Scientific Committee for Eye Diseases ", "Specialized Scientific Committee for Neurological and Psychiatric Diseases", "Specialized Scientific Committee for Neurological and Psychiatric Diseases ", "Specialized Scientific Committee for Veterinary Drugs", "Specialized Scientific Committee of Cardiology and Vascular Diseases and Vascular Diseases", "Specialized Scientific Committee of Ear, Nose, and Throat", "Specialized Scientific Committee of Pediatrics", "Technical Committee of Drug Control", "Technical Committee of Drug Control ", "Veterinary Medicines Committee"]
    return jsonify(sorted(committees))

@app.route('/api/v1/decisions')
@login_required
def get_decisions():
    """Get unique decisions"""
    decisions = [
        "Approved", "Conditionally Approved", "Deferred", "Rejected", "Suspended"
    ]
    return jsonify(sorted(decisions))

@app.route('/api/v1/categories')
@login_required
def get_categories():
    """Get unique categories"""
    categories = [
            "Efficacy", "Regulatory", "Safety", "Post-Market Surveillance", 
            "Manufacturing", "Others", "Formulation", "Toll Manufacturing", 
            "Quality", "Market Launch", "Clinical Study", "Labeling", "Pricing"]
    return jsonify(sorted(categories))

@app.route('/api/v1/search', methods=['POST'])
@login_required
def search():
    """Search and filter the data"""    
    
    # Get search parameters
    data = request.get_json()
    search_query = data.get('search', '').lower().strip()
    committee_filter = data.get('committee', 'all')
    decision_filter = data.get('decision', 'all')
    category_filter = data.get('category', 'all')
    date_from = data.get('date_from', '')
    date_to = data.get('date_to', '')
    page = int(data.get('page', 1))
    per_page = int(data.get('per_page', 20))

    query = """
    SELECT 
        decree.*,
        GROUP_CONCAT(DISTINCT decree_technical_committee_date.date) AS technical_committee_dates,
        GROUP_CONCAT(DISTINCT decree_session_date.date) AS session_dates
    FROM decree
    LEFT JOIN decree_technical_committee_date 
        ON decree.decree_id = decree_technical_committee_date.decree_id
    LEFT JOIN decree_session_date 
        ON decree.decree_id = decree_session_date.decree_id
    """
    filters = []
    if committee_filter != 'all':
        filters.append(f"decree_typeofcommittee LIKE '%{committee_filter}%'")
    if decision_filter != 'all':
        filters.append(f"decree_standarized_decision = '{decision_filter}'")    
    if category_filter != 'all':
        filters.append(f"decree_category = '{category_filter}'")

    # Date range filtering on either table
    if date_from and date_to:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            filters.append(f"""(
                decree_technical_committee_date.date BETWEEN '{start_date}' AND '{end_date}'
            )""")
        except ValueError:
            print("⚠️ Invalid date format")
    elif date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            filters.append(f"""(
                decree_technical_committee_date.date >= '{start_date}'
            )""")
        except ValueError:
            print("⚠️ Invalid date format")
    elif date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            filters.append(f"""(
                decree_technical_committee_date.date <= '{end_date}'
            )""")
        except ValueError:
            print("⚠️ Invalid date format")

    if filters:
        query += " where " + " and ".join(filters)
    query += " group by decree.decree_id"
    print('query', query)
    
    df = pd.read_sql_query(query, engine)
    # conn.close()
    if df is None or df.empty:
        return jsonify({'results': [], 'total': 0, 'error': 'No data loaded', 'success': True})
    
    filtered_df = df.copy() 

    if search_query:
        mask = pd.Series([False] * len(filtered_df))
        if 'decree_active_ingredient' in df.columns:
            mask |= filtered_df['decree_active_ingredient'].astype(str).str.lower().str.contains(search_query, na=False, regex=False)
        filtered_df = filtered_df[mask]
    
    # Pagination
    total = len(filtered_df)
    start = (page - 1) * per_page
    end = start + per_page
    
    # Get paginated results
    results = []
    for idx, row in filtered_df.iloc[start:end].iterrows():
        decision_text = str(row.get('decree_standarized_decision', '')).strip().lower()
        
        # Determine status
        if 'approved' == decision_text:
            status = 'Approved'
            status_class = 'approved'
        elif 'rejected' == decision_text:
            status = 'Rejected'
            status_class = 'rejected'
        else:
            status = 'Pending'
            status_class = 'pending'
        technical_committee_date = None
        if row.get('technical_committee_dates'):
            technical_committee_dates = datetime.strptime(row.get('technical_committee_dates'), "%Y-%m-%d")
            technical_committee_date = technical_committee_dates.strftime("%d-%b-%Y")
        session_dates = None
        if row.get('session_dates'):
            session_date_format = parse_dates_field(row.get('session_dates'))            
            session_dates = ",".join(d.strftime("%m-%b-%Y") for d in session_date_format)
        committee_summary = [item.strip() for item in str(row.get('decree_summary_of_decision', 'N/A')).split("•") if item.strip()]
        results.append({
            'id': idx + 1,
            'year': str(row.get('decree_year', 'N/A')),
            'decree_number': str(row.get('decree_decreenumber', 'N/A')),
            'committee': str(row.get('decree_typeofcommittee', 'N/A')),
            'active_ingredient': str(row.get('decree_active_ingredient', 'N/A')),
            'decision': str(row.get('decree_decision', 'N/A')),
            'standardDecision': str(row.get('decree_standarized_decision', 'N/A')),
            'reason': str(row.get('decree_reason_of_decision', 'N/A')),
            'summary': committee_summary,
            'category': str(row.get('decree_category', 'N/A')),
            'pageno': row.get('decree_pageno', '1'),
            'link': str(row.get('decree_link', '#')).strip(),
            'name_link': str(row.get('decree_name_for_the_link', '#')),
            'decree_country': str(row.get('decree_country', '#')),
            'status': status,
            'status_class': status_class,
            'dateTechnicalCommittee': technical_committee_date,
            'session_dates': session_dates           
        })
    results.sort(key=lambda x: int(x['year']) if x['year'].isdigit() else 0, reverse=True)
    print("=====>", results)
    return jsonify({
        'success': True,
        'results': results,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if total > 0 else 0
    })


@app.route('/api/v1/pharmawarning', methods=['POST'])
@login_required
def pharmawarning():
    """Search and filter the data"""    
    
    # Get search parameters
    data = request.get_json()
    search_query = data.get('search', '').lower().strip()
    page = int(data.get('page', 1))
    per_page = int(data.get('per_page', 20))

    query = """
    SELECT 
        pharma_warning.*
    FROM pharma_warning
    """
    
    df = pd.read_sql_query(query, engine)
    # conn.close()
    if df is None or df.empty:
        return jsonify({'results': [], 'total': 0, 'error': 'No data loaded', 'success': True})
    
    filtered_df = df.copy()
    
    if search_query:
        mask = pd.Series([False] * len(filtered_df))
        if 'pharma_warning_active_ingredient' in df.columns:
            mask |= filtered_df['pharma_warning_active_ingredient'].astype(str).str.lower().str.contains(search_query, na=False, regex=False)
        if 'pharma_warning_purpose_of_decision' in df.columns:
            mask |= filtered_df['pharma_warning_purpose_of_decision'].astype(str).str.lower().str.contains(search_query, na=False, regex=False)
        filtered_df = filtered_df[mask]
    
    # Pagination
    total = len(filtered_df)
    start = (page - 1) * per_page
    end = start + per_page
    
    # Get paginated results
    results = []
    for idx, row in filtered_df.iloc[start:end].iterrows():
        decision_text = str(row.get('decree_standarized_decision', '')).strip().lower()
        
        # Determine status
        if 'approved' == decision_text:
            status = 'Approved'
            status_class = 'approved'
        elif 'rejected' == decision_text:
            status = 'Rejected'
            status_class = 'rejected'
        else:
            status = 'Pending'
            status_class = 'pending'
        results.append({
            'id': idx + 1,
            "pharma_warning_no": row.get('pharma_warning_no'),
            "pharma_warning_decision_date": row.get('pharma_warning_decision_date'),
            "pharma_warning_date_of_update": row.get('pharma_warning_date_of_update'),
            "pharma_warning_class": row.get('pharma_warning_class'),
            "pharma_warning_active_ingredient": row.get('pharma_warning_active_ingredient'),
            "pharma_warning_dosage_form": row.get('pharma_warning_dosage_form'),
            "pharma_warning_route_of_administration": row.get('pharma_warning_route_of_administration'),
            "pharma_warning_grace_period": row.get('pharma_warning_grace_period'),
            "pharma_warning_compliance_deadline": row.get('pharma_warning_compliance_deadline'),
            "pharma_warning_decision_type": row.get('pharma_warning_decision_type'),
            "pharma_warning_purpose_of_decision": row.get('pharma_warning_purpose_of_decision'),
            "pharma_warning_regulatory_reference": row.get('pharma_warning_regulatory_reference'),
            "pharma_warning_page_no": row.get('pharma_warning_page_no'),
            "pharma_warning_link": row.get('pharma_warning_link'),            
        })
    
    return jsonify({
        'success': True,
        'results': results,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if total > 0 else 0
    })

@app.route('/api/v1/drugdata', methods=['POST'])
@login_required
def drugdata():
    """Search and filter the data"""    
    
    # Get search parameters
    data = request.get_json()
    search_query = data.get('search', '').lower().strip()
    page = int(data.get('page', 1))
    per_page = int(data.get('per_page', 20))
    marketingTypes = data.get('marketingTypes', [])
    registrationTypes = data.get('registrationTypes', [])
    marketingStatus = data.get('marketingStatus', [])

    query = """
    SELECT 
        drugdata.*
    FROM drugdata
    """
    
    df = pd.read_sql_query(query, engine)
    # conn.close()
    if df is None or df.empty:
        return jsonify({'results': [], 'total': 0, 'error': 'No data loaded', 'success': True})
    
    filtered_df = df.copy()
    
    if search_query:
        mask = pd.Series([False] * len(filtered_df))
        if 'drugdata_active_ingredient' in df.columns:
            mask |= filtered_df['drugdata_active_ingredient'].astype(str).str.lower().str.contains(search_query, na=False, regex=False)
        if 'pharma_warning_purpose_of_decision' in df.columns:
            mask |= filtered_df['pharma_warning_purpose_of_decision'].astype(str).str.lower().str.contains(search_query, na=False, regex=False)
        if 'drugdata_trade_name' in df.columns:
            mask |= filtered_df['drugdata_trade_name'].astype(str).str.lower().str.contains(search_query, na=False, regex=False)
        if 'drugdata_applicant' in df.columns:
            mask |= filtered_df['drugdata_applicant'].astype(str).str.lower().str.contains(search_query, na=False, regex=False)
        filtered_df = filtered_df[mask]

    # ✅ Filter by marketingTypes
    if marketingTypes and 'drugdata_marketing_type' in df.columns:
        filtered_df = filtered_df[filtered_df['drugdata_marketing_type'].isin(marketingTypes)]

    # ✅ Filter by registrationTypes
    if registrationTypes and 'drugdata_registration_type' in df.columns:
        filtered_df = filtered_df[filtered_df['drugdata_registration_type'].isin(registrationTypes)]

    # ✅ Filter by marketingStatus
    if marketingStatus and 'drugdata_marketing_status' in df.columns:
        filtered_df = filtered_df[filtered_df['drugdata_marketing_status'].isin(marketingStatus)]
        
        
    
    # Pagination
    total = len(filtered_df)
    start = (page - 1) * per_page
    end = start + per_page
    
    # Get paginated results
    results = []
    for idx, row in filtered_df.iloc[start:end].iterrows():
        decision_text = str(row.get('decree_standarized_decision', '')).strip().lower()
        
        # Determine status
        if 'approved' == decision_text:
            status = 'Approved'
            status_class = 'approved'
        elif 'rejected' == decision_text:
            status = 'Rejected'
            status_class = 'rejected'
        else:
            status = 'Pending'
            status_class = 'pending'
        results.append({
            'id': idx + 1,
            "drugdata_reg_no": row.get('drugdata_reg_no'),
            "drugdata_active_ingredient": row.get('drugdata_active_ingredient'),
            "drugdata_trade_name": row.get('drugdata_trade_name'),
            "drugdata_product_type": row.get('drugdata_product_type'),
            "drugdata_dosage_form": row.get('drugdata_dosage_form'),
            "drugdata_shelf_life": row.get('drugdata_shelf_life'),
            "drugdata_route": row.get('drugdata_route'),
            "drugdata_strength": row.get('drugdata_strength'),
            "drugdata_pack_unit": row.get('drugdata_pack_unit'),
            "drugdata_approved_packs": row.get('drugdata_approved_packs'),
            "drugdata_applicant": row.get('drugdata_applicant'),
            "drugdata_registration_no": row.get('drugdata_registration_no'),
            "drugdata_registration_type": row.get('drugdata_registration_type'),
            "drugdata_marketing_type": row.get('drugdata_marketing_type'), 
            "drugdata_marketing_status": row.get('drugdata_marketing_status'),
            "drugdata_license_status": row.get('drugdata_license_status'),
            "drugdata_price_status": row.get('drugdata_price_status'),
            "drugdata_physical_characters": row.get('drugdata_physical_characters'),
            "drugdata_storage_conditions": row.get('drugdata_storage_conditions'),
            "drugdata_registration_data": row.get('drugdata_registration_data'),
            "drugdata_combo_pack": row.get('drugdata_combo_pack'),
            "drugdata_reference": row.get('drugdata_reference'),
            "drugdata_leaflet": row.get('drugdata_leaflet'),
            "drugdata_country": row.get('drugdata_country'),
            "drugdata_comments": row.get('drugdata_comments'),
            "drugdata_page_number": row.get('drugdata_page_number'),
            "drugdata_row_number": row.get('drugdata_row_number'),
        })
    results.sort(key=lambda x: int(x['drugdata_shelf_life']) if x['drugdata_shelf_life'].isdigit() else 0, reverse=True)
    return jsonify({
        'success': True,
        'results': results,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if total > 0 else 0
    })


@app.route('/api/v1/drugdata/<int:drug_id>', methods=['GET'])
@login_required
def drugdatadetails(drug_id):
    """Search and filter the data"""

    drug = db.session.query(Drugdata).filter(Drugdata.drugdata_reg_no == drug_id).first()
    if not drug:
        return {}

    generics = db.session.query(Generics).filter(Generics.generics_reg_no == drug_id).all()
    packages = db.session.query(Package).filter(Package.package_reg_ref == drug_id).all()
    companies = db.session.query(DrugCompany).filter(DrugCompany.drug_company_reg_no == drug_id).all()
    
    drug_data = {k: v for k, v in drug.__dict__.items() if not k.startswith("_")}

    def to_dict(model):
        return {column.name: getattr(model, column.name) for column in model.__table__.columns}

    data = {
        **drug_data,
        "generics": [to_dict(g) for g in generics],
        "packages": [to_dict(p) for p in packages],
        "companies": [to_dict(c) for c in companies],
    }
    
    return jsonify({
        'success': True,
        'results': data
    })


if __name__ == '__main__':
    print("="*60)
    print("RegDec Application with Authentication")
    print("="*60)
    print(f"Working directory: {os.getcwd()}")
    print(f"Python executable: {sys.executable}")
    
    print("="*60 + "\n")
    
    app.run(debug=True, port=5000)