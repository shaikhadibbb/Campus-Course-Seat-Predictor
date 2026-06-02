# features.py
# Feature engineering class for my ML model. 
# Wrote this after my Probability class, sin/cos encoding actually makes sense now.

import numpy as np
import pandas as pd

class FeatureEngineer:
    def __init__(self):
        self.departments = []
        self.is_fitted = False
        # list of features we expect in the final matrix (excluding one-hot dept columns which are added dynamically)
        self.base_features = [
            'total_seats',
            'instructor_rating',
            'is_elective',
            'days_until_semester_start',
            'hour_sin',
            'hour_cos',
            'day_sin',
            'day_cos',
            'seats_per_rating',
            'is_popular_elective'
        ]

    def fit(self, df):
        # learn unique departments to make sure pd.get_dummies doesn't blow up during prediction
        # if a department was not in the prediction input, we still need the column
        self.departments = sorted(list(df['department'].dropna().unique()))
        self.is_fitted = True
        return self

    def transform(self, df_raw):
        if not self.is_fitted:
            raise Exception("Call fit() before transforming, idiot!")

        # operate on a copy to avoid SettingWithCopyWarning from pandas (that warning gives me anxiety)
        df = df_raw.copy()

        # 1. hacky fix for missing ratings
        # df['instructor_rating'] = df['instructor_rating'].fillna(3.0) # why is this breaking? Oh, it's decimal.Decimal from pg. Python is garbage.
        df['instructor_rating'] = df['instructor_rating'].fillna(3.0).astype(float)

        # 2. convert timestamps if they are strings or object types
        reg_dt = pd.to_datetime(df['registration_start'])
        sem_dt = pd.to_datetime(df['semester_start'])

        # 3. days_until_semester_start
        days_diff = (sem_dt - reg_dt).dt.total_seconds() / (24.0 * 3600.0)
        df['days_until_semester_start'] = np.maximum(0.0, days_diff) # clip to 0 so negative dates don't break prediction

        # 4. Cyclical encoding for hour_of_day (sin/cos) and day_of_week (sin/cos)
        hour_of_day = reg_dt.dt.hour
        day_of_week = reg_dt.dt.dayofweek

        df['hour_sin'] = np.sin(2.0 * np.pi * hour_of_day / 24.0)
        df['hour_cos'] = np.cos(2.0 * np.pi * hour_of_day / 24.0)
        df['day_sin'] = np.sin(2.0 * np.pi * day_of_week / 7.0)
        df['day_cos'] = np.cos(2.0 * np.pi * day_of_week / 7.0)

        # 5. seats_per_rating = total_seats / (instructor_rating + 0.1) — hacky but works
        df['seats_per_rating'] = df['total_seats'] / (df['instructor_rating'] + 0.1)

        # 6. is_popular_elective = True if elective AND rating > 4.0
        # Convert bool to int/float because regressor wants numbers
        df['is_elective'] = df['is_elective'].astype(float)
        df['is_popular_elective'] = ((df['is_elective'] == 1.0) & (df['instructor_rating'] > 4.0)).astype(float)

        # Build feature matrix
        X_out = df[self.base_features].copy()

        # 7. One-hot encode department using pd.get_dummies
        dept_dummies = pd.get_dummies(df['department'], prefix='dept')
        
        # align columns: ensure all departments we saw in fit are present
        for dept in self.departments:
            col_name = f"dept_{dept}"
            if col_name in dept_dummies.columns:
                X_out[col_name] = dept_dummies[col_name].astype(float)
            else:
                X_out[col_name] = 0.0

        return X_out

    def fit_transform(self, df):
        self.fit(df)
        
        # separate target variable if it exists in the training set
        if 'hours_to_fill' in df.columns:
            y = df['hours_to_fill'].values
            X = self.transform(df)
            return X, y
        else:
            X = self.transform(df)
            return X
