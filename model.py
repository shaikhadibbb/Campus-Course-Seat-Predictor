# model.py
# Machine Learning model training and prediction pipeline.
# could use XGBoost but scikit-learn is easier to install.
# Wrote this at 3:30am, please let it compile.

import math
import numpy as np
import joblib
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error

def normal_cdf(x, mean, std):
    # probability math is hard, thanks stackoverflow
    if std <= 1e-6:
        return 1.0 if x >= mean else 0.0
    return 0.5 * (1.0 + math.erf((x - mean) / (std * math.sqrt(2.0))))

class CourseFillPredictor:
    def __init__(self):
        self.pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('regressor', GradientBoostingRegressor(n_estimators=100, max_depth=5, random_state=42))
        ])

    def train(self, X, y, registration_starts):
        # Training MUST use TimeSeriesSplit for cross-validation.
        # Regular KFold is wrong here—registration data is sequential and I'll leak future info if I randomize.
        
        # Sort data by registration start time to ensure temporal order
        sort_idx = np.argsort(registration_starts)
        X_sorted = X.iloc[sort_idx].copy()
        y_sorted = y[sort_idx]
        
        print(f"training model on {len(X_sorted)} rows...")
        
        # 5-fold TimeSeriesSplit
        tscv = TimeSeriesSplit(n_splits=5)
        maes = []
        
        for fold, (train_index, test_index) in enumerate(tscv.split(X_sorted)):
            X_tr, X_te = X_sorted.iloc[train_index], X_sorted.iloc[test_index]
            y_tr, y_te = y_sorted[train_index], y_sorted[test_index]
            
            # create temporary pipeline for CV
            fold_pipe = Pipeline([
                ('scaler', StandardScaler()),
                ('regressor', GradientBoostingRegressor(n_estimators=100, max_depth=5, random_state=42))
            ])
            
            fold_pipe.fit(X_tr, y_tr)
            preds = fold_pipe.predict(X_te)
            mae = mean_absolute_error(y_te, preds)
            maes.append(mae)
            
        cv_mean = np.mean(maes)
        cv_std = np.std(maes)
        
        # Print cross-validation MAE. I want to see numbers like "CV MAE: 4.2 hours (+/- 1.8)"
        print(f"CV MAE: {cv_mean:.1f} hours (+/- {cv_std:.1f})")
        
        # Fit final model on ALL sorted data
        self.pipeline.fit(X_sorted, y_sorted)
        print("Model fitted on all data.")

    def predict_with_intervals(self, X_input, num_bootstraps=100):
        # Prediction method MUST return confidence intervals.
        # Use bootstrap sampling from the ensemble trees (grab predictions from individual trees, compute percentiles).
        
        reg = self.pipeline.named_steps['regressor']
        scaler = self.pipeline.named_steps['scaler']
        
        # Scale the features
        X_scaled = scaler.transform(X_input)
        
        # Point predictions
        point_preds = reg.predict(X_scaled)
        
        # Get predictions from individual trees.
        # reg.estimators_ shape is (n_estimators, 1) since we do single-target regression.
        # tree_predictions shape is (n_estimators, n_samples)
        tree_predictions = np.array([tree[0].predict(X_scaled) for tree in reg.estimators_])
        # scale tree outputs by learning rate
        tree_predictions *= reg.learning_rate
        
        # initial base prediction (usually mean of training target)
        base_pred = reg.init_.predict(X_scaled)
        
        # bootstrap sampling from the tree outputs
        bootstrap_preds = []
        np.random.seed(42) # keep things repeatable
        for _ in range(num_bootstraps):
            # draw random tree indices with replacement
            indices = np.random.choice(len(reg.estimators_), size=len(reg.estimators_), replace=True)
            # sum selected trees and add base prediction
            bootstrap_pred = base_pred + tree_predictions[indices].sum(axis=0)
            bootstrap_preds.append(bootstrap_pred)
            
        bootstrap_preds = np.array(bootstrap_preds) # shape (num_bootstraps, n_samples)
        
        results = []
        for i in range(len(X_input)):
            y_p = max(0.0, point_preds[i]) # fill time cannot be negative
            samples = bootstrap_preds[:, i]
            
            # compute percentiles for confidence interval bounds (5% and 95% for 90% confidence interval)
            # 90% CI because 95% is too wide and makes my model look useless
            lower_bound = max(0.0, np.percentile(samples, 5))
            upper_bound = max(0.0, np.percentile(samples, 95))
            
            # calculate normal approximation spread (mean and std dev)
            mu = float(np.mean(samples))
            sigma = float(np.std(samples))
            
            p_fill_24 = normal_cdf(24.0, mu, sigma)
            p_fill_48 = normal_cdf(48.0, mu, sigma)
            
            results.append({
                "predicted_hours": float(round(y_p, 2)),
                "lower_bound": float(round(lower_bound, 2)),
                "upper_bound": float(round(upper_bound, 2)),
                "p_fill_24": float(round(p_fill_24, 4)),
                "p_fill_48": float(round(p_fill_48, 4))
            })
            
        return results

    def save_model(self, filepath):
        joblib.dump(self, filepath)
        print(f"model saved to {filepath}")

    @classmethod
    def load_model(cls, filepath):
        return joblib.load(filepath)
