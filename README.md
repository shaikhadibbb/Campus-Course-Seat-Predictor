# Campus Course Seat Predictor (KU Registrar Lab Project)

I built this because registration at Karnavati University is a complete nightmare. Last semester, CS301 (Operating Systems) filled up in like 3 hours and half my friends missed it and had to take some random history class instead. I wanted a way to predict how fast a course will fill up so students know which classes they need to click on first.

This is my internship project for the registrar's office. It takes registration history, trains a machine learning model, and gives you a dashboard where you can check fill times.

## Tech Stack
- **Database**: PostgreSQL (holds course details and snapshots of filled seats)
- **Backend API**: FastAPI (handles prediction requests and aggregates statistics)
- **ML Model**: Scikit-Learn (uses Gradient Boosting regression to predict hours-to-fill)
- **Frontend**: Plain HTML and Javascript (no React, no bundlers, just inline CSS because it was easier)
- **Container**: Docker Compose to run it all with one command

## How to run it

You need Docker installed. Then just run:

```bash
docker-compose up --build
```

The database will automatically seed itself with F24 and S25 semesters data from `data/historical_enrollment.csv` and `data/messy_catalog.html` on first startup, then it will train the model.

Open your browser and go to:
`http://localhost:8000`

If you want to train the model manually from your terminal, you can run:
```bash
python train.py
```
(make sure you have installed packages from `requirements.txt` first).

## What I learned
- **Cyclic encoding is cool**: Hours (0-23) and days (0-6) repeat. Using sin/cos transformations helped my model understand that 11 PM (23:00) is close to 1 AM (01:00) instead of treating them as opposite ends of a scale.
- **Time-series splits are required**: Normal random cross-validation is wrong for registration. If you shuffle data, the model leaks future data into the past. Using `TimeSeriesSplit` makes it train only on past semesters to predict future ones.
- **Bootstrap uncertainty**: Standard predictions are just a single number, but course fill times are unpredictable. I extracted predictions from all 100 individual trees in the Gradient Boosting ensemble and used their distribution percentiles to get upper and lower bounds.
- **Docker Compose is hard**: Had to write a healthcheck script to make sure the FastAPI backend waits for the Postgres database to start, otherwise it crashes immediately.

## Model performance

Here are the cross-validation metrics I got from my training run:
- **Mean Absolute Error (CV MAE)**: 60.7 hours (+/- 32.8) — yeah, the error is pretty high, but registration behavior is super random and 60 rows is small data.
- **Bootstrap spread**: Standard deviation is around 12.4 hours (CI intervals are pretty wide as a result).

## Known Bugs
- **Retraining Blocks API**: Clicking "Retrain Model" runs synchronously on the backend, blocking the API request for ~20s. It runs in a thread pool so it doesn't freeze the whole server, but it makes the web page loader hang.
- **Wide Confidence Intervals**: The confidence intervals (e.g. [4h - 54h] for a 27h prediction) are often wider than the prediction itself. This happens because Gradient Boosting trees are sequential (residuals) rather than independent like Random Forest, so bootstrapping them breaks their correlation structure and blows up the variance estimation.
- **Mobile Styling**: Mobile Safari has rendering issues where the grids squish on very narrow screens (needs flex-wrap or media queries).
- My date math assumes registration happens in the same timezone as the server, which will break if students are out of state.

## Next steps
- [ ] Add user login so registrar staff can lock the retraining button
- [ ] Connect a live scraper to get actual seat counts instead of dummy csv snapshots
- [ ] Try using XGBoost to see if MAE goes down below 4 hours
- [ ] Fix the css centering on tablets (it looks slightly squished)
