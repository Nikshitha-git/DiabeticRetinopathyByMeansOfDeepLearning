from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from bson import ObjectId
from functools import wraps
import os
import requests
import json
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from PIL import Image

app = Flask(__name__)
CORS(app)

# Configuration
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['REPORT_FOLDER'] = 'reports/'
app.config['SECRET_KEY'] = 'your-super-secret-key-change-this'
app.config['SESSION_TYPE'] = 'filesystem'

# Create folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORT_FOLDER'], exist_ok=True)

# MongoDB Connection
client = MongoClient('mongodb://localhost:27017/')
db = client['dr_database']

# Collections
patients_collection = db['patients']
screenings_collection = db['screenings']
doctors_collection = db['doctors']

# ⚠️ UPDATE THIS WITH YOUR ACTUAL NGROK URL FROM COLAB!
COLAB_MODEL_URL = "https://5279478ee732.ngrok-free.app/predict"

# ===================================
# AUTHENTICATION DECORATORS
# ===================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def doctor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'doctor_email' not in session:
            return jsonify({'error': 'Doctor login required'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ===================================
# HELPER FUNCTIONS
# ===================================

def generate_patient_id():
    count = patients_collection.count_documents({})
    return f"P{str(count + 1).zfill(4)}"

def generate_screening_id():
    count = screenings_collection.count_documents({})
    return f"SCR{str(count + 1).zfill(5)}"

def calculate_severity(prediction):
    severity_map = {
        'No_DR': 0, 'Mild': 1, 'Moderate': 2,
        'Severe': 3, 'Proliferate_DR': 4
    }
    return severity_map.get(prediction, 0)

# ===================================
# PAGE ROUTES
# ===================================

@app.route('/')
def landing():
    """Landing page with login options"""
    return render_template('landing.html')

@app.route('/login')
def login_page():
    """Patient login page"""
    return render_template('login.html')

@app.route('/doctor-login')
def doctor_login_page():
    """Doctor login page"""
    return render_template('doctor_login.html')

@app.route('/patient-dashboard')
@login_required
def patient_dashboard():
    """Patient dashboard - view own screenings"""
    return render_template('patient_dashboard.html')

@app.route('/doctor-dashboard')
def doctor_dashboard():
    """Doctor dashboard - manage all patients"""
    if 'doctor_email' not in session:
        return redirect(url_for('doctor_login_page'))
    return render_template('index.html')

@app.route('/logout')
def logout():
    """Logout"""
    session.clear()
    return redirect(url_for('landing'))

# ===================================
# PATIENT AUTHENTICATION ROUTES
# ===================================

@app.route('/api/patient/register', methods=['POST'])
def patient_register():
    """Register new patient with email"""
    data = request.json
    
    # Check if email exists
    if patients_collection.find_one({'email': data['email']}):
        return jsonify({'error': 'Email already registered'}), 400
    
    # Create patient account
    patient = {
        'patient_id': generate_patient_id(),
        'email': data['email'],
        'password': generate_password_hash(data['password']),
        'name': data['name'],
        'age': int(data['age']),
        'gender': data['gender'],
        'phone': data.get('phone', ''),
        'diabetes_type': data.get('diabetes_type', ''),
        'diabetes_duration': int(data.get('diabetes_duration', 0)),
        'registration_date': datetime.now()
    }
    
    patients_collection.insert_one(patient)
    
    return jsonify({
        'success': True,
        'message': 'Registration successful! Please login.',
        'patient_id': patient['patient_id']
    }), 201

@app.route('/api/patient/login', methods=['POST'])
def patient_login():
    """Patient login"""
    data = request.json
    patient = patients_collection.find_one({'email': data['email']})
    
    if patient and check_password_hash(patient['password'], data['password']):
        session['user_email'] = patient['email']
        session['user_name'] = patient['name']
        session['patient_id'] = patient['patient_id']
        session['user_type'] = 'patient'
        
        return jsonify({
            'success': True,
            'redirect': '/patient-dashboard',
            'patient': {
                'name': patient['name'],
                'email': patient['email'],
                'patient_id': patient['patient_id']
            }
        }), 200
    
    return jsonify({'error': 'Invalid email or password'}), 401

# ===================================
# DOCTOR AUTHENTICATION ROUTES
# ===================================

@app.route('/api/doctor/register', methods=['POST'])
def doctor_register():
    """Register new doctor"""
    data = request.json
    
    if doctors_collection.find_one({'email': data['email']}):
        return jsonify({'error': 'Email already registered'}), 400
    
    doctor = {
        'email': data['email'],
        'password': generate_password_hash(data['password']),
        'full_name': data['full_name'],
        'specialization': data.get('specialization', 'Ophthalmologist'),
        'license_number': data.get('license_number', ''),
        'created_at': datetime.now()
    }
    
    doctors_collection.insert_one(doctor)
    return jsonify({'success': True, 'message': 'Doctor registered successfully'}), 201

@app.route('/api/doctor/login', methods=['POST'])
def doctor_login():
    """Doctor login"""
    data = request.json
    doctor = doctors_collection.find_one({'email': data['email']})
    
    if doctor and check_password_hash(doctor['password'], data['password']):
        session['doctor_email'] = doctor['email']
        session['doctor_name'] = doctor['full_name']
        session['user_type'] = 'doctor'
        
        return jsonify({
            'success': True,
            'redirect': '/doctor-dashboard'
        }), 200
    
    return jsonify({'error': 'Invalid credentials'}), 401

# ===================================
# PATIENT PORTAL ROUTES (LOGIN REQUIRED)
# ===================================

@app.route('/api/patient/profile', methods=['GET'])
@login_required
def get_patient_profile():
    """Get logged-in patient profile"""
    patient = patients_collection.find_one({'email': session['user_email']})
    
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    
    patient['_id'] = str(patient['_id'])
    patient.pop('password', None)
    
    return jsonify(patient), 200

@app.route('/api/patient/screening/upload', methods=['POST'])
@login_required
def patient_upload_screening():
    """Patient uploads their own retinal image"""
    try:
        patient_id = session['patient_id']
        eye_side = request.form.get('eye_side', 'Right')
        file = request.files['file']
        
        # Save image
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{patient_id}_{timestamp}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Send to Colab model
        with open(filepath, 'rb') as img_file:
            files = {'file': img_file}
            response = requests.post(
                COLAB_MODEL_URL,
                files=files,
                headers={"ngrok-skip-browser-warning": "true"},
                timeout=60
            )
        
        if response.status_code != 200:
            return jsonify({'error': 'Model prediction failed'}), 500
        
        result = response.json()
        severity = calculate_severity(result['prediction'])
        needs_referral = severity >= 2
        
        # Save screening
        screening = {
            'screening_id': generate_screening_id(),
            'patient_id': patient_id,
            'patient_email': session['user_email'],
            'screening_date': datetime.now(),
            'eye_side': eye_side,
            'image_path': filepath,
            'prediction': result['prediction'],
            'confidence': result.get('confidence', 0) * 100,
            'severity_level': severity,
            'requires_referral': needs_referral,
            'probabilities': result.get('probabilities', {})
        }
        
        screenings_collection.insert_one(screening)
        
        if severity >= 3:
            print(f"⚠️ ALERT: Severe case for {session['user_email']}")
        
        return jsonify({
            'success': True,
            'screening_id': screening['screening_id'],
            'prediction': result['prediction'],
            'confidence': screening['confidence'],
            'probabilities': result.get('probabilities', {}),
            'requires_referral': needs_referral,
            'severity_level': severity
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/patient/screenings', methods=['GET'])
@login_required
def get_patient_screenings():
    """Get all screenings for logged-in patient"""
    screenings = list(screenings_collection.find(
        {'patient_email': session['user_email']}
    ).sort('screening_date', -1))
    
    for screening in screenings:
        screening['_id'] = str(screening['_id'])
        screening['screening_date'] = screening['screening_date'].isoformat()
    
    return jsonify(screenings), 200

@app.route('/api/patient/screening/<screening_id>/report', methods=['GET'])
@login_required
def get_patient_report(screening_id):
    """Download patient's own screening report"""
    screening = screenings_collection.find_one({
        'screening_id': screening_id,
        'patient_email': session['user_email']
    })
    
    if not screening:
        return jsonify({'error': 'Report not found'}), 404
    
    patient = patients_collection.find_one({'email': session['user_email']})
    
    # Generate PDF
    pdf_filename = f"report_{screening_id}.pdf"
    pdf_path = os.path.join(app.config['REPORT_FOLDER'], pdf_filename)
    
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 20)
    c.drawString(1*inch, height - 1*inch, "Diabetic Retinopathy Screening Report")
    
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1*inch, height - 1.5*inch, "Patient Information")
    c.setFont("Helvetica", 12)
    y = height - 1.8*inch
    c.drawString(1*inch, y, f"Name: {patient['name']}")
    c.drawString(1*inch, y - 0.3*inch, f"Patient ID: {patient['patient_id']}")
    
    y -= 1.2*inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1*inch, y, "Screening Results")
    c.setFont("Helvetica", 12)
    y -= 0.3*inch
    c.drawString(1*inch, y, f"Date: {screening['screening_date'].strftime('%Y-%m-%d %H:%M')}")
    
    y -= 0.6*inch
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1*inch, y, f"Diagnosis: {screening['prediction']}")
    c.setFont("Helvetica", 12)
    c.drawString(1*inch, y - 0.3*inch, f"Confidence: {screening['confidence']:.2f}%")
    
    if screening['requires_referral']:
        c.setFillColorRGB(1, 0, 0)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1*inch, y - 0.8*inch, "⚠️ Please consult an ophthalmologist")
    
    c.save()
    return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)

# ===================================
# DOCTOR PORTAL ROUTES (LOGIN REQUIRED)
# ===================================

@app.route('/api/patients', methods=['GET'])
@doctor_required
def get_all_patients():
    """Doctor: Get all patients"""
    patients = list(patients_collection.find())
    for patient in patients:
        patient['_id'] = str(patient['_id'])
        patient.pop('password', None)
    return jsonify(patients), 200

@app.route('/api/patients/<patient_id>', methods=['GET'])
@doctor_required
def get_patient_details(patient_id):
    """Doctor: Get patient details with history"""
    patient = patients_collection.find_one({'patient_id': patient_id})
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    
    screenings = list(screenings_collection.find({'patient_id': patient_id}).sort('screening_date', -1))
    
    patient['_id'] = str(patient['_id'])
    patient.pop('password', None)
    
    for screening in screenings:
        screening['_id'] = str(screening['_id'])
        screening['screening_date'] = screening['screening_date'].isoformat()
    
    return jsonify({'patient': patient, 'screenings': screenings}), 200

@app.route('/api/dashboard/stats', methods=['GET'])
@doctor_required
def get_dashboard_stats():
    """Doctor: Dashboard statistics"""
    total_patients = patients_collection.count_documents({})
    total_screenings = screenings_collection.count_documents({})
    high_risk = screenings_collection.count_documents({'requires_referral': True})
    
    pipeline = [{'$group': {'_id': '$prediction', 'count': {'$sum': 1}}}]
    severity_dist = list(screenings_collection.aggregate(pipeline))
    severity_data = {item['_id']: item['count'] for item in severity_dist}
    
    avg_pipeline = [{'$group': {'_id': None, 'avg_confidence': {'$avg': '$confidence'}}}]
    avg_result = list(screenings_collection.aggregate(avg_pipeline))
    avg_confidence = avg_result[0]['avg_confidence'] if avg_result else 0
    
    high_risk_screenings = list(screenings_collection.find(
        {'requires_referral': True}
    ).sort('screening_date', -1).limit(10))
    
    high_risk_patients = []
    for screening in high_risk_screenings:
        patient = patients_collection.find_one({'patient_id': screening['patient_id']})
        if patient:
            high_risk_patients.append({
                'patient_id': screening['patient_id'],
                'patient_name': patient.get('name', 'Unknown'),
                'prediction': screening['prediction'],
                'date': screening['screening_date'].isoformat()
            })
    
    return jsonify({
        'total_patients': total_patients,
        'total_screenings': total_screenings,
        'high_risk_count': high_risk,
        'severity_distribution': severity_data,
        'high_risk_patients': high_risk_patients,
        'average_confidence': round(avg_confidence, 2)
    }), 200

# ===================================
# PUBLIC ROUTES (NO LOGIN REQUIRED)
# ===================================

@app.route('/api/patients', methods=['POST'])
def add_patient_public():
    """Register new patient (public access)"""
    data = request.json
    
    patient = {
        'patient_id': generate_patient_id(),
        'name': data['name'],
        'age': int(data['age']),
        'gender': data['gender'],
        'phone': data.get('phone', ''),
        'email': data.get('email', ''),
        'diabetes_type': data.get('diabetes_type', ''),
        'diabetes_duration': int(data.get('diabetes_duration', 0)),
        'registration_date': datetime.now()
    }
    
    result = patients_collection.insert_one(patient)
    
    return jsonify({
        'message': 'Patient registered successfully',
        'patient_id': patient['patient_id']
    }), 201

@app.route('/api/patients/public', methods=['GET'])
def get_patients_public():
    """Get all patients (public access)"""
    patients = list(patients_collection.find())
    for patient in patients:
        patient['_id'] = str(patient['_id'])
        if 'registration_date' in patient:
            patient['registration_date'] = patient['registration_date'].isoformat()
        patient.pop('password', None)
    return jsonify(patients), 200

@app.route('/api/screening', methods=['POST'])
def perform_screening_public():
    """Perform DR screening (public access)"""
    import time
    start_time = time.time()
    
    try:
        patient_id = request.form.get('patient_id')
        eye_side = request.form.get('eye_side', 'Right')
        file = request.files['file']
        
        patient = patients_collection.find_one({'patient_id': patient_id})
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{patient_id}_{timestamp}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        print(f"📸 Image saved: {filepath}")
        print(f"🔬 Sending to model: {COLAB_MODEL_URL}")
        
        with open(filepath, 'rb') as img_file:
            files = {'file': img_file}
            response = requests.post(
                COLAB_MODEL_URL,
                files=files,
                headers={"ngrok-skip-browser-warning": "true"},
                timeout=60
            )
        
        print(f"📊 Model response: {response.status_code}")
        
        if response.status_code != 200:
            return jsonify({
                'error': f'Model prediction failed: {response.status_code}',
                'details': response.text
            }), 500
        
        result = response.json()
        print(f"✅ Prediction: {result}")
        
        severity = calculate_severity(result['prediction'])
        needs_referral = severity >= 2
        processing_time = time.time() - start_time
        
        screening = {
            'screening_id': generate_screening_id(),
            'patient_id': patient_id,
            'screening_date': datetime.now(),
            'eye_side': eye_side,
            'image_path': filepath,
            'prediction': result['prediction'],
            'confidence': result.get('confidence', 0) * 100,
            'severity_level': severity,
            'requires_referral': needs_referral,
            'probabilities': result.get('probabilities', {}),
            'processing_time': processing_time
        }
        
        screenings_collection.insert_one(screening)
        
        if severity >= 3:
            print(f"⚠️ ALERT: Severe DR case - Patient {patient_id}")
        
        return jsonify({
            'success': True,
            'screening_id': screening['screening_id'],
            'prediction': result['prediction'],
            'confidence': screening['confidence'],
            'probabilities': result.get('probabilities', {}),
            'requires_referral': needs_referral,
            'severity_level': severity,
            'processing_time': processing_time
        }), 200
        
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Model timeout. Is Colab running?'}), 500
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Connection failed: {str(e)}'}), 500
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/screenings/<patient_id>/history', methods=['GET'])
def get_screening_history_public(patient_id):
    """Get screening history (public access)"""
    screenings = list(screenings_collection.find(
        {'patient_id': patient_id}
    ).sort('screening_date', -1))
    
    for screening in screenings:
        screening['_id'] = str(screening['_id'])
        screening['screening_date'] = screening['screening_date'].isoformat()
    
    return jsonify(screenings), 200

@app.route('/api/dashboard/stats/public', methods=['GET'])
def get_dashboard_stats_public():
    """Dashboard stats (public access)"""
    total_patients = patients_collection.count_documents({})
    total_screenings = screenings_collection.count_documents({})
    high_risk = screenings_collection.count_documents({'requires_referral': True})
    
    pipeline = [{'$group': {'_id': '$prediction', 'count': {'$sum': 1}}}]
    severity_dist = list(screenings_collection.aggregate(pipeline))
    severity_data = {item['_id']: item['count'] for item in severity_dist}
    
    high_risk_screenings = list(screenings_collection.find(
        {'requires_referral': True}
    ).sort('screening_date', -1).limit(10))
    
    high_risk_patients = []
    for screening in high_risk_screenings:
        patient = patients_collection.find_one({'patient_id': screening['patient_id']})
        if patient:
            high_risk_patients.append({
                'patient_id': screening['patient_id'],
                'patient_name': patient.get('name', 'Unknown'),
                'prediction': screening['prediction'],
                'date': screening['screening_date'].isoformat()
            })
    
    avg_pipeline = [{'$group': {'_id': None, 'avg_confidence': {'$avg': '$confidence'}}}]
    avg_result = list(screenings_collection.aggregate(avg_pipeline))
    avg_confidence = avg_result[0]['avg_confidence'] if avg_result else 0
    
    return jsonify({
        'total_patients': total_patients,
        'total_screenings': total_screenings,
        'high_risk_count': high_risk,
        'severity_distribution': severity_data,
        'high_risk_patients': high_risk_patients,
        'average_confidence': round(avg_confidence, 2)
    }), 200

@app.route('/api/report/patient/<screening_id>', methods=['GET'])
def generate_report_public(screening_id):
    """Generate PDF report (public access)"""
    screening = screenings_collection.find_one({'screening_id': screening_id})
    if not screening:
        return jsonify({'error': 'Screening not found'}), 404
    
    patient = patients_collection.find_one({'patient_id': screening['patient_id']})
    
    pdf_filename = f"report_{screening_id}.pdf"
    pdf_path = os.path.join(app.config['REPORT_FOLDER'], pdf_filename)
    
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 20)
    c.drawString(1*inch, height - 1*inch, "Diabetic Retinopathy Screening Report")
    
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1*inch, height - 1.5*inch, "Patient Information")
    c.setFont("Helvetica", 12)
    y = height - 1.8*inch
    c.drawString(1*inch, y, f"Patient ID: {patient['patient_id']}")
    c.drawString(1*inch, y - 0.3*inch, f"Name: {patient['name']}")
    c.drawString(1*inch, y - 0.6*inch, f"Age: {patient['age']} | Gender: {patient['gender']}")
    
    y -= 1.2*inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1*inch, y, "Screening Results")
    c.setFont("Helvetica", 12)
    y -= 0.3*inch
    c.drawString(1*inch, y, f"Date: {screening['screening_date'].strftime('%Y-%m-%d %H:%M')}")
    c.drawString(1*inch, y - 0.3*inch, f"Eye: {screening['eye_side']}")
    
    y -= 0.9*inch
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1*inch, y, f"Diagnosis: {screening['prediction']}")
    c.setFont("Helvetica", 12)
    c.drawString(1*inch, y - 0.3*inch, f"Confidence: {screening['confidence']:.2f}%")
    
    if screening['requires_referral']:
        c.setFillColorRGB(1, 0, 0)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1*inch, y - 0.8*inch, "⚠️ REFERRAL RECOMMENDED")
        c.setFillColorRGB(0, 0, 0)
    
    c.setFont("Helvetica", 10)
    c.drawString(1*inch, 0.5*inch, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    c.save()
    
    return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)

# ===================================
# RUN APPLICATION
# ===================================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 DR SCREENING SYSTEM STARTING...")
    print("="*60)
    print(f"📊 MongoDB: Connected to 'dr_database'")
    print(f"🏥 Server: http://localhost:5000")
    print(f"🔬 Model URL: {COLAB_MODEL_URL}")
    print("="*60)
    print("\n⚠️  CHECKLIST:")
    print("  ✓ MongoDB Compass is connected")
    print("  ✓ Colab model is running with ngrok")
    print("  ✓ COLAB_MODEL_URL is updated above")
    print("\n📱 ACCESS:")
    print("  • Main: http://localhost:5000")
    print("  • Patient Login: http://localhost:5000/login")
    print("  • Doctor Login: http://localhost:5000/doctor-login")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
