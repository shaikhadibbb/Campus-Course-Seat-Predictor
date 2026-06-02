# main.py
# FastAPI backend API. One big file containing everything.
# Please do not crash during demonstration.

import os
from datetime import datetime, date
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import pandas as pd
import joblib

from database import Database
from features import FeatureEngineer
from model import CourseFillPredictor

app = FastAPI(title="Campus Course Seat Predictor API")

# Add CORS middleware so my frontend can talk to it
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables for model state (tired of passing them around)
predictor = None
feature_engineer = None
db = Database()

# Pydantic validation models
class PredictRequest(BaseModel):
    course_code: str = Field(..., example="CS-301-A")
    course_name: str = Field(..., example="Operating Systems")
    department: str = Field(..., example="CS")
    total_seats: int = Field(..., example=40)
    instructor_rating: float = Field(..., example=4.5)
    is_elective: bool = Field(..., example=False)
    registration_start: datetime = Field(..., example="2026-06-03T09:00:00")
    semester_start: date = Field(..., example="2026-06-20")

class PredictResponse(BaseModel):
    predicted_hours: float
    lower_bound: float
    upper_bound: float
    p_fill_24: float
    p_fill_48: float
    recommendation: str

def get_semester_code(dt: datetime) -> str:
    # helper to guess semester based on registration opening month
    # e.g., Jun 2026 -> F26, Nov 2026 -> S27, Jan 2026 -> S26
    year_str = str(dt.year)[2:]
    if 4 <= dt.month <= 9:
        return f"F{year_str}"
    elif dt.month >= 10:
        return f"S{int(year_str) + 1}"
    else:
        return f"S{year_str}"

def load_ml_models():
    global predictor, feature_engineer
    model_path = os.path.join(os.path.dirname(__file__), "model.pkl")
    fe_path = os.path.join(os.path.dirname(__file__), "feature_engineer.pkl")
    
    if os.path.exists(model_path) and os.path.exists(fe_path):
        try:
            predictor = CourseFillPredictor.load_model(model_path)
            feature_engineer = joblib.load(fe_path)
            print("Successfully loaded model and feature engineer pickles.")
            return True
        except Exception as e:
            print(f"Failed to load model pickles: {e}. Will retrain.")
    return False

@app.on_event("startup")
def startup_event():
    # 1. Initialize and seed PostgreSQL DB
    db.init_db()
    db.seed_data()
    
    # 2. Try loading models, or train if missing
    if not load_ml_models():
        print("ML models missing or corrupted. Triggering initial training...")
        from train import main as train_model
        try:
            train_model()
            load_ml_models()
        except Exception as e:
            print(f"Startup training crashed: {e}")
            
    # 3. Pre-generate and cache predictions if database predictions table is empty
    global predictor, feature_engineer
    if predictor and feature_engineer:
        try:
            pred_count = db.execute_query("SELECT COUNT(*) as cnt FROM predictions;")
            if pred_count and pred_count[0]["cnt"] == 0:
                print("Predictions cache is empty on startup. Pre-generating for all courses...")
                courses = db.get_courses()
                if courses:
                    courses_df = pd.DataFrame(courses)
                    X_courses = feature_engineer.transform(courses_df)
                    preds = predictor.predict_with_intervals(X_courses)
                    for idx, row in courses_df.iterrows():
                        pred = preds[idx]
                        db.store_prediction(
                            course_code=row["course_code"],
                            semester=row["semester"],
                            pred_hours=pred["predicted_hours"],
                            lower=pred["lower_bound"],
                            upper=pred["upper_bound"],
                            p_24=pred["p_fill_24"],
                            p_48=pred["p_fill_48"]
                        )
                    print("Startup predictions cache generation successful.")
        except Exception as e:
            print(f"Failed to generate startup predictions cache: {e}")

# Serve the static frontend at root /
@app.get("/", response_class=HTMLResponse)
def read_root():
    static_index = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(static_index):
        with open(static_index, "r") as f:
            return HTMLResponse(content=f.read())
    else:
        return HTMLResponse(content="<h1>static/index.html not found! Run from correct directory.</h1>", status_code=404)

@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    global predictor, feature_engineer
    if not predictor or not feature_engineer:
        raise HTTPException(status_code=503, detail="ML model is not trained/loaded. Retrain via /refresh first.")
        
    try:
        # Determine semester
        sem = get_semester_code(req.registration_start)
        
        # Save or update course metadata in DB
        q_course = """
            INSERT INTO courses (course_code, course_name, department, total_seats, instructor_rating, is_elective, semester, registration_start, semester_start)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (course_code, semester) DO UPDATE SET
                course_name = EXCLUDED.course_name,
                department = EXCLUDED.department,
                total_seats = EXCLUDED.total_seats,
                instructor_rating = EXCLUDED.instructor_rating,
                is_elective = EXCLUDED.is_elective,
                registration_start = EXCLUDED.registration_start,
                semester_start = EXCLUDED.semester_start
            RETURNING id;
        """
        # rating can be empty if NaN, map NaN/None properly
        rating_val = req.instructor_rating if req.instructor_rating > 0 else None
        db.execute_query(q_course, (
            req.course_code, req.course_name, req.department, req.total_seats,
            rating_val, req.is_elective, sem, req.registration_start, req.semester_start
        ))
        
        # Format input for FeatureEngineer (dataframe)
        input_data = [{
            "course_code": req.course_code,
            "course_name": req.course_name,
            "department": req.department,
            "total_seats": req.total_seats,
            "instructor_rating": rating_val,
            "is_elective": req.is_elective,
            "semester": sem,
            "registration_start": req.registration_start,
            "semester_start": datetime.combine(req.semester_start, datetime.min.time())
        }]
        
        df_input = pd.DataFrame(input_data)
        
        # Preprocess features
        X_pred = feature_engineer.transform(df_input)
        
        # Run prediction
        preds = predictor.predict_with_intervals(X_pred)
        p = preds[0]
        
        # Select colored text recommendation box text
        # Red border for urgent (<12h), orange for high priority (<48h), green for safe
        hours = p["predicted_hours"]
        if hours < 12.0:
            rec = "URGENT: Register immediately! Fills in less than 12 hours."
        elif hours < 48.0:
            rec = "HIGH PRIORITY: Register on day 1. Fills in less than 48 hours."
        else:
            rec = "SAFE: Fills slowly. You should be fine for a couple of days."
            
        # Store prediction outputs in cache table
        db.store_prediction(
            course_code=req.course_code,
            semester=sem,
            pred_hours=p["predicted_hours"],
            lower=p["lower_bound"],
            upper=p["upper_bound"],
            p_24=p["p_fill_24"],
            p_48=p["p_fill_48"]
        )
        
        return PredictResponse(
            predicted_hours=p["predicted_hours"],
            lower_bound=p["lower_bound"],
            upper_bound=p["upper_bound"],
            p_fill_24=p["p_fill_24"],
            p_fill_48=p["p_fill_48"],
            recommendation=rec
        )
    except Exception as e:
        # Pydantic validation handles client side errors, this is for pipeline crashes
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")

@app.get("/courses")
def get_courses():
    try:
        courses = db.get_courses()
        return courses
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboard/stats")
def get_stats():
    try:
        stats = db.get_dashboard_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/refresh")
def refresh_models():
    # manual trigger to reload and retrain
    try:
        print("manual trigger to retrain model...")
        from train import main as retrain
        retrain()
        
        # reload into memory
        success = load_ml_models()
        if success:
            return {"message": "Database re-seeded and Gradient Boosting model retrained successfully!"}
        else:
            raise HTTPException(status_code=500, detail="Retraining worked but loading pickled model failed.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount static directory for static assets (js, images)
# Serve index.html from root directly above, but mount for other resources just in case
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
