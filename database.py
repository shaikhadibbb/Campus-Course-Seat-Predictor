# database.py
# python database wrapper using psycopg2. I hate SQL but here we go.
# comments written at 2am under caffeine overload.

import os
import re
import csv
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

import getpass

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "course_predictor")
DB_USER = os.getenv("DB_USER", getpass.getuser())
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

class Database:
    def __init__(self):
        self.conn = self.get_conn()

    def get_conn(self):
        # try connection, dont crash if database container is not ready yet
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=5
            )
            return conn
        except Exception as e:
            # this works, dont touch it
            print(f"db connection died, idk why: {e}")
            return None

    def execute_query(self, query, params=None):
        if not self.conn or self.conn.closed:
            self.conn = self.get_conn()
        if not self.conn:
            print("No connection, skipping query")
            return None
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                if cur.description:
                    return cur.fetchall()
                self.conn.commit()
                return []
        except Exception as e:
            print(f"query failed but keeping going: {e}")
            if self.conn:
                self.conn.rollback()
            return None

    def init_db(self):
        # read schema.sql and run it
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        if not os.path.exists(schema_path):
            print(f"where is schema.sql? checked {schema_path}")
            return
        
        print("initializing database tables...")
        with open(schema_path, "r") as f:
            schema_sql = f.read()
        
        # split by semicolon because sometimes execute doesn't like multiple statements
        statements = schema_sql.split(";")
        for stmt in statements:
            if stmt.strip():
                self.execute_query(stmt)
        print("database tables initialized.")

    def seed_data(self):
        # check if already seeded
        result = self.execute_query("SELECT COUNT(*) as cnt FROM courses;")
        if result and result[0]["cnt"] > 0:
            print("database already seeded, skipping seeding.")
            return

        print("seeding database...")
        courses_map = {} # maps (course_code, semester) -> course_id

        # 1. Parse messy_catalog.html
        catalog_path = os.path.join(os.path.dirname(__file__), "data", "messy_catalog.html")
        instructor_ratings = {
            "Dr. Chen": 4.5, "Dr. Smith": 3.8, "Dr. Alan": 4.8, "Dr. Jones": 3.5,
            "Dr. Gauss": 4.2, "Dr. Euler": 2.5, "Dr. Poe": 4.9, "Dr. Gibbon": 3.2,
            "Dr. Curie": 4.0, "Dr. Nobel": 3.0
        }
        elective_courses = {"LIT-150"}

        if os.path.exists(catalog_path):
            print("parsing messy_catalog.html...")
            with open(catalog_path, "r") as f:
                html = f.read()
            
            # regex pattern to match table rows for courses
            # <td><b>CS-101</b> - Intro to Programming (CS)</td>
            # <td align='center'>A</td>
            # <td>Dr. Chen</td>
            # <td>Total Seats: <span id='cap_CS-101_A'>40</span></td>
            pattern = re.compile(
                r"<b>([A-Z0-9-]+)</b>\s*-\s*([^<]+?)\s*\(([A-Z]+)\).*?<td align='center'>([A-Z])</td>\s*<td>([^<]+)</td>\s*<td>Total Seats: <span[^>]*>(\d+)</span>",
                re.DOTALL
            )
            matches = pattern.findall(html)
            
            for match in matches:
                base_code, name, dept, sec, instructor, seats = match
                course_code = f"{base_code}-{sec}"
                total_seats = int(seats)
                instructor = instructor.strip()
                rating = instructor_ratings.get(instructor, 3.0) # default 3.0 rating
                is_elective = base_code in elective_courses
                
                # We seed F24 and S25 semesters for these catalog courses
                for sem in ["F24", "S25"]:
                    reg_start = datetime(2024, 6, 10, 9, 0, 0) if sem == "F24" else datetime(2025, 11, 5, 9, 0, 0)
                    sem_start = datetime(2024, 7, 1).date() if sem == "F24" else datetime(2025, 11, 20).date()
                    
                    q = """
                        INSERT INTO courses (course_code, course_name, department, total_seats, instructor_rating, is_elective, semester, registration_start, semester_start)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                    """
                    res = self.execute_query(q, (course_code, name.strip(), dept, total_seats, rating, is_elective, sem, reg_start, sem_start))
                    if res:
                        courses_map[(course_code, sem)] = res[0]["id"]
            print(f"seeded {len(courses_map)} catalog course sections.")
        else:
            print("messy_catalog.html not found, cannot seed catalog courses.")

        # 2. Parse historical_enrollment.csv
        history_path = os.path.join(os.path.dirname(__file__), "data", "historical_enrollment.csv")
        if os.path.exists(history_path):
            print("loading historical enrollment data...")
            history_rows = []
            with open(history_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sem = row["semester_code"]
                    course_code = f"{row['course_code']}-{row['section_code']}"
                    timestamp = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
                    seats_filled = int(row["seats_filled"])
                    
                    course_id = courses_map.get((course_code, sem))
                    if course_id:
                        day_of_week = timestamp.weekday()
                        hour_of_day = timestamp.hour
                        history_rows.append((course_id, seats_filled, timestamp, day_of_week, hour_of_day))
            
            # batch insert to speed up
            if history_rows:
                q = """
                    INSERT INTO seat_history (course_id, seats_filled, timestamp, day_of_week, hour_of_day)
                    VALUES (%s, %s, %s, %s, %s);
                """
                if not self.conn or self.conn.closed:
                    self.conn = self.get_conn()
                if self.conn:
                    try:
                        with self.conn.cursor() as cur:
                            cur.executemany(q, history_rows)
                        self.conn.commit()
                        print(f"seeded {len(history_rows)} seat history rows.")
                    except Exception as e:
                        print(f"batch insert of history failed: {e}")
                        self.conn.rollback()
        else:
            print("historical_enrollment.csv not found.")

        # 3. Parse data/sample_data.csv and seed simulated history
        sample_path = os.path.join(os.path.dirname(__file__), "data", "sample_data.csv")
        if os.path.exists(sample_path):
            print("loading sample courses from sample_data.csv...")
            sample_seeded = 0
            with open(sample_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    course_code = row["course_code"]
                    name = row["course_name"]
                    dept = row["department"]
                    total_seats = int(row["total_seats"])
                    rating_str = row["instructor_rating"]
                    rating = float(rating_str) if rating_str else None # dirty ratings handled
                    is_elective = row["is_elective"].lower() == "true"
                    sem = row["semester"]
                    reg_start = datetime.strptime(row["registration_start"], "%Y-%m-%d %H:%M:%S")
                    sem_start = datetime.strptime(row["semester_start"], "%Y-%m-%d").date()
                    actual_hours = float(row["actual_hours_to_fill"])
                    
                    # skip if we already loaded it via catalog F24/S25
                    if (course_code, sem) in courses_map:
                        continue
                    
                    # insert course
                    q = """
                        INSERT INTO courses (course_code, course_name, department, total_seats, instructor_rating, is_elective, semester, registration_start, semester_start)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (course_code, semester) DO UPDATE SET instructor_rating = EXCLUDED.instructor_rating
                        RETURNING id;
                    """
                    res = self.execute_query(q, (course_code, name, dept, total_seats, rating, is_elective, sem, reg_start, sem_start))
                    if res:
                        course_id = res[0]["id"]
                        sample_seeded += 1
                        
                        # simulate seat history snapshots
                        # we generate ~15 snapshots between t=0 and t=actual_hours
                        history_to_insert = []
                        num_snapshots = 15
                        
                        # growth factor. if rating > 4, fills faster at beginning. if low rating, fills later
                        # default growth factor is 1.0 (linear)
                        r_val = rating if rating else 3.0
                        power = 0.6 if r_val > 4.2 else (1.5 if r_val < 2.5 else 1.0)
                        
                        for i in range(num_snapshots + 1):
                            fraction = i / num_snapshots
                            h_offset = fraction * actual_hours
                            ts = reg_start + timedelta(hours=h_offset)
                            
                            # actual seats filled calculation
                            if actual_hours >= 200.0:
                                # failed to fill course
                                seats_f = int(total_seats * 0.75 * (fraction ** power))
                            else:
                                seats_f = int(total_seats * (fraction ** power))
                                if i == num_snapshots:
                                    seats_f = total_seats
                            
                            history_to_insert.append((
                                course_id,
                                min(seats_f, total_seats),
                                ts,
                                ts.weekday(),
                                ts.hour
                            ))
                            
                        # execute batch insert for this course history
                        q_hist = """
                            INSERT INTO seat_history (course_id, seats_filled, timestamp, day_of_week, hour_of_day)
                            VALUES (%s, %s, %s, %s, %s);
                        """
                        if not self.conn or self.conn.closed:
                            self.conn = self.get_conn()
                        if self.conn:
                            try:
                                with self.conn.cursor() as cur:
                                    cur.executemany(q_hist, history_to_insert)
                                self.conn.commit()
                            except Exception as e:
                                print(f"failed seeding simulated history: {e}")
                                self.conn.rollback()
                                
            print(f"seeded {sample_seeded} sample course sections.")
        else:
            print("sample_data.csv not found.")
            
    def get_training_data(self):
        # pulls training data (joins courses + history)
        # groups by course, computes target variable hours_to_fill
        print("fetching courses for training data...")
        courses = self.execute_query("SELECT * FROM courses;")
        if not courses:
            return []
            
        print("fetching seat history snapshots...")
        history = self.execute_query("SELECT * FROM seat_history ORDER BY course_id, timestamp;")
        if not history:
            return []
            
        # organize history by course_id
        hist_by_course = {}
        for row in history:
            cid = row["course_id"]
            if cid not in hist_by_course:
                hist_by_course[cid] = []
            hist_by_course[cid].append(row)
            
        training_rows = []
        for course in courses:
            cid = course["id"]
            snapshots = hist_by_course.get(cid, [])
            if not snapshots:
                continue
                
            start_time = course["registration_start"]
            total_seats = course["total_seats"]
            
            # find first timestamp where seats_filled >= total_seats
            fill_time = None
            for snap in snapshots:
                if snap["seats_filled"] >= total_seats:
                    fill_time = snap["timestamp"]
                    break
                    
            if fill_time:
                hours_to_fill = (fill_time - start_time).total_seconds() / 3600.0
            else:
                # did not fill, so cap at max duration of recorded snapshots for this course
                max_time = snapshots[-1]["timestamp"]
                duration = (max_time - start_time).total_seconds() / 3600.0
                # cap it at 168.0 (1 week) or just use duration
                hours_to_fill = max(duration, 168.0)
                
            # add row to training data
            row_data = {
                "course_code": course["course_code"],
                "course_name": course["course_name"],
                "department": course["department"],
                "total_seats": total_seats,
                "instructor_rating": float(course["instructor_rating"]) if course["instructor_rating"] is not None else None,
                "is_elective": course["is_elective"],
                "semester": course["semester"],
                "registration_start": start_time,
                "semester_start": datetime.combine(course["semester_start"], datetime.min.time()),
                "hours_to_fill": hours_to_fill
            }
            training_rows.append(row_data)
            
        return training_rows

    def get_courses(self):
        # lists all current courses with their latest prediction
        # SQL with DISTINCT ON is super fast, thanks StackOverflow
        q = """
            SELECT DISTINCT ON (c.course_code, c.semester)
                c.id, c.course_code, c.course_name, c.department, c.total_seats, 
                c.instructor_rating, c.is_elective, c.semester, c.registration_start, c.semester_start,
                p.predicted_hours, p.lower_bound, p.upper_bound, p.p_fill_24, p.p_fill_48
            FROM courses c
            LEFT JOIN predictions p ON c.course_code = p.course_code AND c.semester = p.semester
            ORDER BY c.course_code, c.semester, p.created_at DESC;
        """
        res = self.execute_query(q)
        return res if res else []

    def store_prediction(self, course_code, semester, pred_hours, lower, upper, p_24, p_48):
        q = """
            INSERT INTO predictions (course_code, semester, predicted_hours, lower_bound, upper_bound, p_fill_24, p_fill_48)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
        """
        self.execute_query(q, (course_code, semester, pred_hours, lower, upper, p_24, p_48))

    def get_dashboard_stats(self):
        # aggregated stats for the dashboard section
        # total courses
        c_count = self.execute_query("SELECT COUNT(*) as count FROM courses;")
        total_courses = c_count[0]["count"] if c_count else 0
        
        # predictions made today
        p_today = self.execute_query("SELECT COUNT(*) as count FROM predictions WHERE created_at >= CURRENT_DATE;")
        pred_today = p_today[0]["count"] if p_today else 0
        
        # training target stats: avg fill time, fastest filling course
        # we can calculate it by calling get_training_data
        training_data = self.get_training_data()
        
        avg_fill_time = 0.0
        fastest_course = "N/A"
        min_time = 999999.0
        
        if training_data:
            times = [r["hours_to_fill"] for r in training_data]
            avg_fill_time = sum(times) / len(times)
            
            for r in training_data:
                # only count courses that actually filled (i.e. fill_time < 168 or just minimum overall)
                if r["hours_to_fill"] < min_time:
                    min_time = r["hours_to_fill"]
                    fastest_course = f"{r['course_code']} ({r['hours_to_fill']:.1f}h)"
        
        if min_time == 999999.0:
            fastest_course = "None yet"
            
        return {
            "total_courses": int(total_courses),
            "avg_fill_time": float(round(avg_fill_time, 1)),
            "fastest_filling_course": fastest_course,
            "predictions_made_today": int(pred_today)
        }
