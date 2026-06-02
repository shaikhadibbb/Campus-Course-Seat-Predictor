# train.py
# Standalone script to train the course seat fill predictor model.
# I run this when I get new historical registration data.

import os
import joblib
import pandas as pd
from database import Database
from features import FeatureEngineer
from model import CourseFillPredictor

def main():
    db = Database()
    
    # if the database is not ready or has no data, let's init and seed it
    # just in case this script is run before the web server seeds it.
    conn = db.get_conn()
    if not conn:
        print("Could not connect to database. Is PostgreSQL running?")
        return
        
    db.init_db()
    db.seed_data()
    
    # 1. Load data from PostgreSQL using Database.get_training_data()
    raw_data = db.get_training_data()
    if not raw_data:
        print("No training data found in database. Seed failed?")
        return
        
    df = pd.DataFrame(raw_data)
    print(f"loaded {len(df)} rows")
    
    # 2. Process with FeatureEngineer
    fe = FeatureEngineer()
    X, y = fe.fit_transform(df)
    
    # print engineered features count
    print(f"engineered {X.shape[1]} features")
    
    # 3. Train with CourseFillPredictor
    print("training...")
    predictor = CourseFillPredictor()
    predictor.train(X, y, df['registration_start'])
    
    # 4. Save model files
    model_path = os.path.join(os.path.dirname(__file__), "model.pkl")
    fe_path = os.path.join(os.path.dirname(__file__), "feature_engineer.pkl")
    
    predictor.save_model(model_path)
    joblib.dump(fe, fe_path)
    
    print("done, saved to model.pkl")
    
    # 5. Pre-calculate predictions for all courses in the DB and cache them
    print("pre-generating predictions for database courses...")
    courses = db.get_courses()
    if courses:
        courses_df = pd.DataFrame(courses)
        # transform courses using our feature engineer
        X_courses = fe.transform(courses_df)
        preds = predictor.predict_with_intervals(X_courses)
        
        # save predictions to database
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
        print("saved cached predictions for all courses.")

if __name__ == "__main__":
    main()
