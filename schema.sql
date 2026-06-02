-- schema.sql
-- student seat predictor DB structure

DROP TABLE IF EXISTS predictions CASCADE;
DROP TABLE IF EXISTS seat_history CASCADE;
DROP TABLE IF EXISTS courses CASCADE;

-- courses metadata
CREATE TABLE courses (
    id SERIAL PRIMARY KEY,
    course_code VARCHAR(50) NOT NULL,
    course_name VARCHAR(150) NOT NULL,
    department VARCHAR(50) NOT NULL,
    total_seats INTEGER NOT NULL,
    instructor_rating NUMERIC(3, 2), -- 1.5 to 5.0, can be null (dirty data)
    is_elective BOOLEAN NOT NULL DEFAULT FALSE,
    semester VARCHAR(20) NOT NULL, -- e.g., 'F24', 'S25'
    registration_start TIMESTAMP NOT NULL,
    semester_start DATE NOT NULL,
    UNIQUE(course_code, semester)
);

-- seat snapshots over time
CREATE TABLE seat_history (
    id SERIAL PRIMARY KEY,
    course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
    seats_filled INTEGER NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    day_of_week INTEGER NOT NULL, -- 0 (Mon) to 6 (Sun)
    hour_of_day INTEGER NOT NULL  -- 0 to 23
);

-- store predictions so backend doesn't recompute every time
CREATE TABLE predictions (
    id SERIAL PRIMARY KEY,
    course_code VARCHAR(50) NOT NULL,
    semester VARCHAR(20) NOT NULL,
    predicted_hours NUMERIC(6, 2) NOT NULL,
    lower_bound NUMERIC(6, 2) NOT NULL,
    upper_bound NUMERIC(6, 2) NOT NULL,
    p_fill_24 NUMERIC(5, 4) NOT NULL,
    p_fill_48 NUMERIC(5, 4) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- idk if this index helps but whatever
CREATE INDEX idx_seat_history_course_id ON seat_history(course_id);
CREATE INDEX idx_seat_history_timestamp ON seat_history(timestamp);
CREATE INDEX idx_predictions_code_sem ON predictions(course_code, semester);
