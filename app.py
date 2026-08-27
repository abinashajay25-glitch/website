import os
import re
import json
import uuid
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "nextstep-secret-key-2026")
DATABASE = os.environ.get("DATABASE_PATH", "opportunities.db")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

VALID_CATEGORIES = {"Hackathon", "Expo", "Internship", "Course", "Job", "Certification", "Workshop"}

OFFICIAL_DOMAINS = (
    "summerofcode.withgoogle.com",
    "hashcode.withgoogle.com",
    "hacktoberfest.com",
    "www.spaceappschallenge.org",
    "www.outreachy.org",
    "www.coursera.org",
    "skillsbuild.org",
    "learn.microsoft.com",
    "www.freecodecamp.org",
    "www.microsoft.com",
    "careers.google.com",
    "jobs.careers.microsoft.com",
    "github.com",
    "www.deeplearning.ai",
    "www.edx.org",
    "iitm.ac.in",
    "annauniv.edu",
    "imaginecup.microsoft.com",
    "www.kaggle.com",
    "aws.amazon.com",
    "education.oracle.com",
    "nptel.ac.in",
    "swayam.gov.in",
    "www.netacad.com",
    "www.mlh.com",
)

UNTRUSTED_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd")


def today_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_text(value):
    return " ".join(str(value or "").strip().split())


def _safe_url(value):
    value = (value or "").strip()
    if not value:
        return ""
    return value if value.startswith("http://") or value.startswith("https://") else f"https://{value}"


def calculate_trust_score(url, source_verified_flag=0):
    cleaned = _safe_url(url).lower()
    if not cleaned:
        return {
            "trust_score": 50,
            "trust_badge": "Partially Verified",
            "domain": "Unknown",
            "is_https": False,
            "reason": "URL not specified. Verify details directly with issuer."
        }
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    is_https = parsed.scheme == "https"
    
    if any(shortener in host for shortener in UNTRUSTED_SHORTENERS):
        return {
            "trust_score": 40,
            "trust_badge": "Unverified",
            "domain": host,
            "is_https": is_https,
            "reason": "URL uses a link shortener. Proceed with caution."
        }
        
    is_official = any(host == domain or host.endswith(f".{domain}") for domain in OFFICIAL_DOMAINS) or bool(source_verified_flag)
    
    if is_official and is_https:
        return {
            "trust_score": 100,
            "trust_badge": "Verified",
            "domain": host,
            "is_https": True,
            "reason": "Verified official platform domain from globally recognized institution."
        }
    elif is_https and (host.endswith(".edu") or host.endswith(".ac.in") or host.endswith(".gov") or host.endswith(".org") or host.endswith(".com")):
        return {
            "trust_score": 85,
            "trust_badge": "Partially Verified",
            "domain": host,
            "is_https": True,
            "reason": "Secure HTTPS portal from registered domain. Check program eligibility."
        }
    else:
        return {
            "trust_score": 50,
            "trust_badge": "Unverified",
            "domain": host or "Non-HTTPS",
            "is_https": is_https,
            "reason": "Source requires manual verification. Review domain details before applying."
        }


def ensure_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            organization TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            skills TEXT,
            eligibility TEXT,
            location TEXT,
            start_date TEXT,
            deadline TEXT,
            registration_url TEXT,
            source_website TEXT,
            last_updated TEXT,
            source_verified INTEGER DEFAULT 0,
            link TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            profile_json TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            current_batch TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendation_history (
            user_id INTEGER NOT NULL,
            opportunity_id INTEGER NOT NULL,
            recommended_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            viewed_at TEXT,
            status TEXT NOT NULL DEFAULT 'recommended',
            batch_id TEXT,
            PRIMARY KEY (user_id, opportunity_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            opportunity_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'saved',
            notes TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, opportunity_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON recommendation_history(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_user ON user_applications(user_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    
    # Clean up expired opportunities & duplicates
    conn.execute("DELETE FROM opportunities WHERE deadline < ?", (today_iso(),))
    
    # Migrate legacy plaintext passwords to hashed passwords safely
    users = conn.execute("SELECT id, password FROM users").fetchall()
    for u in users:
        pwd = u["password"]
        if not pwd.startswith("scrypt:") and not pwd.startswith("pbkdf2:"):
            hashed = generate_password_hash(pwd)
            conn.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, u["id"]))


def get_seed_data():
    today = today_iso()
    return [
        {
            "title": "Google Summer of Code 2026",
            "organization": "Google",
            "category": "Internship",
            "description": "Work with open-source mentors on real software engineering projects and gain industry experience.",
            "skills": "Python, JavaScript, Git, Open Source, C++",
            "eligibility": "Open to 1st, 2nd, 3rd, and 4th year undergraduate & graduate students.",
            "location": "Remote",
            "start_date": "2026-10-01",
            "deadline": "2026-10-15",
            "registration_url": "https://summerofcode.withgoogle.com/",
            "source_website": "https://summerofcode.withgoogle.com/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Outreachy Open Source Fellowship",
            "organization": "Outreachy",
            "category": "Internship",
            "description": "Contribute to open source and open science with structured mentorship and a stipend.",
            "skills": "Python, SQL, Git, Documentation, Data Science",
            "eligibility": "Open to college students and early career software developers.",
            "location": "Remote",
            "start_date": "2026-11-01",
            "deadline": "2026-10-30",
            "registration_url": "https://www.outreachy.org/",
            "source_website": "https://www.outreachy.org/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "NASA Space Apps Challenge 2026",
            "organization": "NASA",
            "category": "Hackathon",
            "description": "Solve space and Earth science challenges in an international team-based hackathon using open NASA data.",
            "skills": "Python, Data Science, Machine Learning, GIS, AI",
            "eligibility": "Open to 1st, 2nd, 3rd, and 4th year students across all engineering branches.",
            "location": "Hybrid",
            "start_date": "2026-10-03",
            "deadline": "2026-10-20",
            "registration_url": "https://www.spaceappschallenge.org/",
            "source_website": "https://www.spaceappschallenge.org/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Google Hash Code Global Competition",
            "organization": "Google",
            "category": "Hackathon",
            "description": "Team-based programming contest focused on optimization and algorithmic problem solving.",
            "skills": "Algorithms, C++, Java, Python, Data Structures",
            "eligibility": "Open to university students interested in programming challenges.",
            "location": "Remote",
            "start_date": "2026-11-06",
            "deadline": "2026-11-05",
            "registration_url": "https://hashcode.withgoogle.com/",
            "source_website": "https://hashcode.withgoogle.com/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Hacktoberfest 2026",
            "organization": "DigitalOcean & GitHub",
            "category": "Hackathon",
            "description": "Contribute to GitHub open-source repositories and learn collaborative software development.",
            "skills": "Git, GitHub, JavaScript, Python, Open Source",
            "eligibility": "Open to all students learning coding and software engineering.",
            "location": "Remote",
            "start_date": "2026-10-01",
            "deadline": "2026-10-31",
            "registration_url": "https://hacktoberfest.com/",
            "source_website": "https://hacktoberfest.com/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Chennai College AI & Innovation Hackathon",
            "organization": "IIT Madras Innovation Centre",
            "category": "Hackathon",
            "description": "Build practical AI, IoT, and Web solutions with industry mentors at IIT Madras.",
            "skills": "Python, Machine Learning, JavaScript, Git, Problem Solving",
            "eligibility": "Open to college students in Chennai and surrounding regions.",
            "location": "Chennai",
            "start_date": "2026-10-24",
            "deadline": "2026-10-18",
            "registration_url": "https://www.iitm.ac.in/",
            "source_website": "https://www.iitm.ac.in/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Anna University Engineering Expo",
            "organization": "Anna University",
            "category": "Expo",
            "description": "Demonstrate student robotics, software, and hardware innovation projects to industry leaders.",
            "skills": "Robotics, Python, Hardware, Web Development, Presentation",
            "eligibility": "Open to undergraduate engineering students.",
            "location": "Chennai",
            "start_date": "2026-11-14",
            "deadline": "2026-11-10",
            "registration_url": "https://www.annauniv.edu/",
            "source_website": "https://www.annauniv.edu/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Google Cybersecurity Professional Certificate",
            "organization": "Google via Coursera",
            "category": "Certification",
            "description": "Master cybersecurity foundations, Linux, Python, threat intelligence, and SIEM tools.",
            "skills": "Cybersecurity, Networking, Linux, Python, Security Operations",
            "eligibility": "Beginner friendly, open to all students.",
            "location": "Online",
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://www.coursera.org/professional-certificates/google-cybersecurity",
            "source_website": "https://www.coursera.org/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "IBM AI Engineering & Fundamentals",
            "organization": "IBM SkillsBuild",
            "category": "Course",
            "description": "Learn artificial intelligence core principles, machine learning models, and prompt engineering.",
            "skills": "AI, Machine Learning, Python, Prompt Engineering",
            "eligibility": "Open to all students interested in AI and Data Science.",
            "location": "Online",
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://skillsbuild.org/",
            "source_website": "https://skillsbuild.org/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Microsoft Azure Cloud Fundamentals (AZ-900)",
            "organization": "Microsoft Learn",
            "category": "Certification",
            "description": "Master cloud concepts, Azure architecture, cloud security, and cloud deployment models.",
            "skills": "Cloud, Azure, DevOps, Networking, Security",
            "eligibility": "Beginner friendly for students building cloud expertise.",
            "location": "Online",
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://learn.microsoft.com/en-us/credentials/certifications/azure-fundamentals/",
            "source_website": "https://learn.microsoft.com/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "DeepLearning.AI Machine Learning Specialization",
            "organization": "DeepLearning.AI",
            "category": "Course",
            "description": "Comprehensive ML program covering supervised learning, neural networks, TensorFlow, and best practices.",
            "skills": "Machine Learning, Python, Data Science, AI, Mathematics",
            "eligibility": "Recommended for AI & CS students with basic Python knowledge.",
            "location": "Online",
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://www.deeplearning.ai/courses/machine-learning-specialization/",
            "source_website": "https://www.deeplearning.ai/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Google Data Analytics Professional Certificate",
            "organization": "Google via Coursera",
            "category": "Certification",
            "description": "Hands-on training in SQL, R, Tableau, spreadsheet analysis, and data visualization.",
            "skills": "Data Science, SQL, Data Analysis, Visualization, Python",
            "eligibility": "Open to all students looking for data science careers.",
            "location": "Online",
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://www.coursera.org/professional-certificates/google-data-analytics",
            "source_website": "https://www.coursera.org/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Software Engineering Early Career Program",
            "organization": "Google Careers",
            "category": "Job",
            "description": "Entry-level software engineering positions and rotational development programs.",
            "skills": "Python, Java, Data Structures, C++, Software Engineering",
            "eligibility": "Open to 3rd and 4th year students and recent graduates.",
            "location": "Hybrid",
            "start_date": "2026-10-01",
            "deadline": "2026-12-15",
            "registration_url": "https://careers.google.com/jobs/results/",
            "source_website": "https://careers.google.com/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Microsoft Student Ambassador & Developer Roles",
            "organization": "Microsoft",
            "category": "Job",
            "description": "Explore software engineering, cloud solutions, and student developer leadership roles.",
            "skills": "Python, Cloud, Azure, C#, Web Development",
            "eligibility": "Open to university students across all engineering branches.",
            "location": "Remote",
            "start_date": "2026-10-01",
            "deadline": "2026-12-20",
            "registration_url": "https://jobs.careers.microsoft.com/",
            "source_website": "https://jobs.careers.microsoft.com/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "Kaggle Global ML Competitions",
            "organization": "Kaggle",
            "category": "Hackathon",
            "description": "Solve real-world machine learning challenges on live public datasets and build your Kaggle rank.",
            "skills": "Python, Machine Learning, Data Science, SQL, AI",
            "eligibility": "Open to all students and machine learning developers.",
            "location": "Online",
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://www.kaggle.com/competitions",
            "source_website": "https://www.kaggle.com/",
            "last_updated": today,
            "source_verified": 1,
        },
        {
            "title": "SWAYAM & NPTEL Advanced Data Structures",
            "organization": "NPTEL / IIT Kharagpur",
            "category": "Course",
            "description": "Official course on algorithms, graph theory, dynamic programming, and data structures.",
            "skills": "Data Structures, Algorithms, C++, Java, Problem Solving",
            "eligibility": "Open to all CS, IT, and AI students.",
            "location": "Online",
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://nptel.ac.in/",
            "source_website": "https://nptel.ac.in/",
            "last_updated": today,
            "source_verified": 1,
        }
    ]


def seed_opportunities(conn):
    for item in get_seed_data():
        existing = conn.execute(
            "SELECT id FROM opportunities WHERE title = ? AND organization = ?",
            (item["title"], item["organization"]),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE opportunities SET last_updated = ?, source_verified = ?, source_website = ?, registration_url = ?, deadline = ? WHERE id = ?",
                (item["last_updated"], int(item.get("source_verified", 0)), item["source_website"], item["registration_url"], item["deadline"], existing["id"]),
            )
            continue
        conn.execute(
            """
            INSERT INTO opportunities (
                title, organization, category, description, skills, eligibility,
                location, start_date, deadline, registration_url, source_website,
                last_updated, source_verified, link
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["title"],
                item["organization"],
                item["category"],
                item["description"],
                item["skills"],
                item["eligibility"],
                item["location"],
                item["start_date"],
                item["deadline"],
                item["registration_url"],
                item["source_website"],
                item["last_updated"],
                int(item.get("source_verified", 0)),
                item["registration_url"],
            ),
        )


def init_db():
    conn = get_db()
    ensure_schema(conn)
    seed_opportunities(conn)
    conn.commit()
    conn.close()


init_db()


def _current_user_id():
    return session.get("user_id")


@app.route("/")
def home():
    if not _current_user_id():
        return redirect(url_for("login"))
    return render_template("index.html")


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/profile")
def profile():
    if not _current_user_id():
        return redirect(url_for("login"))
    return render_template("index.html")


@app.route("/opportunities")
def opportunities_page():
    if not _current_user_id():
        return redirect(url_for("login"))
    return render_template("index.html")


@app.route("/api/auth", methods=["POST"])
def auth_api():
    payload = request.get_json(force=True) or {}
    action = (payload.get("action") or "login").lower()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password are required."}), 400

    conn = get_db()
    if action == "signup":
        try:
            hashed = generate_password_hash(password)
            conn.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, hashed))
            conn.commit()
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            session["user_id"] = user["id"]
            conn.close()
            return jsonify({"status": "success", "message": f"Account created for {email}."})
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"status": "error", "message": "Email is already registered. Please sign in."}), 400

    user = conn.execute("SELECT id, email, password FROM users WHERE email = ?", (email,)).fetchone()
    if user:
        stored_password = user["password"]
        # Check hashed password or auto-upgrade legacy plaintext password
        if check_password_hash(stored_password, password) or stored_password == password:
            if not stored_password.startswith("scrypt:") and not stored_password.startswith("pbkdf2:"):
                new_hashed = generate_password_hash(password)
                conn.execute("UPDATE users SET password = ? WHERE id = ?", (new_hashed, user["id"]))
                conn.commit()
            session["user_id"] = user["id"]
            conn.close()
            return jsonify({"status": "success", "message": f"Logged in as {user['email']}"})
    
    conn.close()
    return jsonify({"status": "error", "message": "Invalid email or password."}), 401


@app.route("/api/profile", methods=["GET", "POST"])
def profile_api():
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"authenticated": False, "completed": False, "profile": {}}), 401
    conn = get_db()
    if request.method == "POST":
        profile = request.get_json(force=True) or {}
        required = ["department", "skills", "interests", "career", "location"]
        completed = all(profile.get(key) for key in required)
        conn.execute(
            "INSERT INTO user_profiles (user_id, profile_json, completed, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id) DO UPDATE SET profile_json=excluded.profile_json, completed=excluded.completed, updated_at=CURRENT_TIMESTAMP, current_batch=NULL",
            (user_id, json.dumps(profile), int(completed)),
        )
        conn.commit()
    row = conn.execute("SELECT profile_json, completed FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    profile = json.loads(row["profile_json"]) if row else {}
    required = ["department", "skills", "interests", "career", "location"]
    completion = int(sum(bool(profile.get(key)) for key in required) / len(required) * 100) if required else 0
    return jsonify({"authenticated": True, "completed": bool(row and row["completed"]), "completion": completion, "profile": profile})


def _as_list(value):
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [part.strip().lower() for item in value for part in str(item).replace("/", " ").split(",") if part.strip()]
    return [part.strip().lower() for part in str(value).replace("/", " ").split(",") if part.strip()]


def profile_matches_eligibility(profile, opportunity):
    eligibility = (opportunity.get("eligibility") or "").lower()
    if not eligibility or "open to all" in eligibility or "beginner friendly" in eligibility:
        return True
    year = str(profile.get("year") or "").lower()
    if year and any(t in eligibility for t in ["1st", "2nd", "3rd", "4th", "year"]):
        allowed_map = {"1": ["1st", "first", "1"], "2": ["2nd", "second", "2"], "3": ["3rd", "third", "3"], "4": ["4th", "fourth", "4"]}
        matched_year = False
        for yr, keywords in allowed_map.items():
            if any(k in eligibility for k in keywords):
                if year == yr:
                    matched_year = True
                    break
        if not matched_year and any(k in eligibility for k in ["1st", "2nd", "3rd", "4th"]):
            return False
    return True


def analyze_skill_gap(profile_skills_list, opportunity_skills_str, all_courses):
    profile_set = set([s.lower() for s in profile_skills_list])
    req_skills = [s.strip() for s in opportunity_skills_str.split(",") if s.strip()] if opportunity_skills_str else []
    
    matching_skills = []
    missing_skills = []
    
    for req in req_skills:
        if req.lower() in profile_set or any(ps in req.lower() or req.lower() in ps for ps in profile_set):
            matching_skills.append(req)
        else:
            missing_skills.append(req)
            
    recommended_courses = []
    if missing_skills:
        for course in all_courses:
            course_skills = (course.get("skills") or "").lower()
            if any(ms.lower() in course_skills for ms in missing_skills):
                recommended_courses.append({
                    "id": course["id"],
                    "title": course["title"],
                    "organization": course["organization"],
                    "url": course.get("registration_url") or course.get("link") or "#",
                    "covers_skill": [ms for ms in missing_skills if ms.lower() in course_skills]
                })
    return {
        "matching_skills": matching_skills,
        "missing_skills": missing_skills,
        "recommended_courses": recommended_courses[:2]
    }


def generate_action_plan(opportunity, skill_gap):
    missing = skill_gap["missing_skills"]
    deadline = opportunity.get("deadline", "Upcoming")
    
    week1 = f"Fill Skill Gap: Learn {missing[0]}" if missing else "Review prerequisites and research past project submissions."
    week2 = "Portfolio Build: Complete a small prototype or project repository showcasing relevant skills."
    week3 = f"Submission Phase: Complete official registration before deadline ({deadline})."
    week4 = "Evaluation & Interview Prep: Review core engineering principles and prepare for technical assessment."
    
    return [
        {"week": "Week 1 (Days 1-7)", "title": "Foundation & Skill Prep", "action": week1},
        {"week": "Week 2 (Days 8-14)", "title": "Hands-on Project & Resume", "action": week2},
        {"week": "Week 3 (Days 15-21)", "title": "Final Application & Team Entry", "action": week3},
        {"week": "Week 4 (Days 22-30)", "title": "Review & Next Steps", "action": week4},
    ]


def calculate_ai_ranking(profile, opportunity, all_courses):
    profile = profile or {}
    prof_skills = _as_list(profile.get("skills"))
    opp_skills = (opportunity.get("skills") or "")
    
    skill_gap = analyze_skill_gap(prof_skills, opp_skills, all_courses)
    
    score = 40  # Base fit
    
    # Skill overlap calculation (up to 30 pts)
    req_count = len(skill_gap["matching_skills"]) + len(skill_gap["missing_skills"])
    if req_count > 0:
        score += int((len(skill_gap["matching_skills"]) / req_count) * 35)
    else:
        score += 15
        
    # Department fit (up to 15 pts)
    dept = (profile.get("department") or "").lower()
    opp_text = (opportunity.get("title", "") + " " + opportunity.get("description", "") + " " + opportunity.get("eligibility", "")).lower()
    if dept and (dept in opp_text or any(token in opp_text for token in dept.split() if len(token) > 2)):
        score += 15
        
    # Interest fit (up to 10 pts)
    interests = _as_list(profile.get("interests") or profile.get("interest"))
    if any(interest in opp_text for interest in interests):
        score += 10
        
    # Career Goal fit (up to 10 pts)
    career = (profile.get("career") or "").lower()
    category = (opportunity.get("category") or "").lower()
    if career and (career in category or category in career or career in opp_text):
        score += 10
        
    match_score = min(98, max(55, score))
    
    # Generate transparent "Why This Match?" rationale
    dept_str = profile.get("department") or "Engineering"
    year_str = profile.get("year") or "Student"
    
    match_reasons = []
    if skill_gap["matching_skills"]:
        match_reasons.append(f"Matches your existing skills in {', '.join(skill_gap['matching_skills'][:3])}")
    if dept in opp_text or "ai" in dept or "computer" in dept:
        match_reasons.append(f"Directly aligns with your {dept_str} background")
    if career:
        match_reasons.append(f"Supports your career goal in {profile.get('career')}")
        
    why_match = f"Suitable for Year {year_str} {dept_str} students. " + " ".join(match_reasons) + "."
    
    trust_info = calculate_trust_score(opportunity.get("registration_url") or opportunity.get("source_website"), opportunity.get("source_verified"))
    action_plan = generate_action_plan(opportunity, skill_gap)
    
    return {
        "match_score": match_score,
        "why_match": why_match,
        "trust_info": trust_info,
        "skill_gap": skill_gap,
        "action_plan": action_plan
    }


@app.route("/api/opportunities")
def opportunities():
    category = (request.args.get("category") or "").strip()
    search = (request.args.get("search") or request.args.get("q") or "").strip().lower()
    sort = (request.args.get("sort") or "deadline").lower()

    conn = get_db()
    query = "SELECT * FROM opportunities WHERE deadline >= ?"
    params = [today_iso()]
    
    if category and category.lower() != "all":
        query += " AND LOWER(category) = LOWER(?)"
        params.append(category)
    if search:
        query += " AND (LOWER(title) LIKE ? OR LOWER(organization) LIKE ? OR LOWER(skills) LIKE ? OR LOWER(description) LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like, like])
        
    query += " ORDER BY deadline ASC, title ASC"
    rows = conn.execute(query, params).fetchall()
    
    # Fetch courses for skill gap mapping
    course_rows = conn.execute("SELECT * FROM opportunities WHERE category IN ('Course', 'Certification')").fetchall()
    all_courses = [dict(r) for r in course_rows]
    conn.close()

    data = []
    for row in rows:
        item = dict(row)
        item["registration_url"] = item.get("registration_url") or item.get("link") or ""
        item["source_verified"] = bool(item.get("source_verified", 0))
        item["trust_info"] = calculate_trust_score(item["registration_url"], item["source_verified"])
        item["skill_gap"] = analyze_skill_gap([], item.get("skills", ""), all_courses)
        data.append(item)

    response = jsonify(data)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.route("/api/match", methods=["POST"])
def match():
    payload = request.get_json(force=True) or {}
    user_id = _current_user_id()
    conn = get_db()
    
    saved_profile = None
    if user_id:
        profile_row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        if profile_row and profile_row["profile_json"]:
            saved_profile = json.loads(profile_row["profile_json"])
            
    profile = saved_profile or payload
    if not profile or not profile.get("department"):
        conn.close()
        return jsonify({"status": "profile_incomplete", "message": "Complete your profile to unlock personalized AI matches.", "completion": 0}), 409

    rows = conn.execute("SELECT * FROM opportunities WHERE deadline >= ? ORDER BY deadline ASC", (today_iso(),)).fetchall()
    course_rows = conn.execute("SELECT * FROM opportunities WHERE category IN ('Course', 'Certification')").fetchall()
    all_courses = [dict(r) for r in course_rows]
    conn.close()

    results = []
    for row in rows:
        opportunity = dict(row)
        if not profile_matches_eligibility(profile, opportunity):
            continue
            
        ai_data = calculate_ai_ranking(profile, opportunity, all_courses)
        opportunity.update(ai_data)
        opportunity["registration_url"] = opportunity.get("registration_url") or opportunity.get("link") or ""
        results.append(opportunity)

    results.sort(key=lambda x: -x["match_score"])
    return jsonify(results)


@app.route("/api/nlp-search", methods=["POST", "GET"])
def nlp_search():
    if request.method == "POST":
        data = request.get_json(force=True) or {}
        query = data.get("query", "").strip()
    else:
        query = request.args.get("q", "").strip()

    if not query:
        return jsonify({"status": "error", "message": "Search query is required."}), 400

    # Extract intent from natural language string
    intent = {
        "raw_query": query,
        "detected_category": "All",
        "detected_skills": [],
        "detected_dept": "",
        "detected_year": ""
    }

    q_lower = query.lower()
    if "hackathon" in q_lower:
        intent["detected_category"] = "Hackathon"
    elif "course" in q_lower or "learn" in q_lower:
        intent["detected_category"] = "Course"
    elif "internship" in q_lower or "job" in q_lower:
        intent["detected_category"] = "Internship"
    elif "certif" in q_lower:
        intent["detected_category"] = "Certification"

    skill_keywords = ["python", "ml", "machine learning", "ai", "sql", "java", "javascript", "react", "git", "cloud", "aws", "cybersecurity", "c++"]
    for sk in skill_keywords:
        if sk in q_lower:
            intent["detected_skills"].append(sk.title())

    if "ai & ds" in q_lower or "ai" in q_lower or "data science" in q_lower:
        intent["detected_dept"] = "AI & Data Science"
    elif "cs" in q_lower or "computer science" in q_lower:
        intent["detected_dept"] = "Computer Science"

    if "1st" in q_lower or "1st year" in q_lower:
        intent["detected_year"] = "1"
    elif "2nd" in q_lower or "2nd year" in q_lower:
        intent["detected_year"] = "2"
    elif "3rd" in q_lower or "3rd year" in q_lower:
        intent["detected_year"] = "3"
    elif "4th" in q_lower or "4th year" in q_lower:
        intent["detected_year"] = "4"

    # Search database matching intent
    conn = get_db()
    rows = conn.execute("SELECT * FROM opportunities WHERE deadline >= ?", (today_iso(),)).fetchall()
    course_rows = conn.execute("SELECT * FROM opportunities WHERE category IN ('Course', 'Certification')").fetchall()
    all_courses = [dict(r) for r in course_rows]
    conn.close()

    mock_profile = {
        "department": intent["detected_dept"] or "Computer Science",
        "year": intent["detected_year"] or "2",
        "skills": intent["detected_skills"] or ["Python"],
        "interests": ["AI", "Software Development"],
        "career": intent["detected_category"]
    }

    results = []
    for r in rows:
        opp = dict(r)
        if intent["detected_category"] != "All" and opp["category"].lower() != intent["detected_category"].lower():
            continue
        ai_data = calculate_ai_ranking(mock_profile, opp, all_courses)
        opp.update(ai_data)
        opp["registration_url"] = opp.get("registration_url") or opp.get("link") or ""
        results.append(opp)

    results.sort(key=lambda x: -x["match_score"])
    return jsonify({
        "intent": intent,
        "results": results
    })


@app.route("/api/learning-path", methods=["GET"])
def learning_path():
    career_goal = (request.args.get("goal") or "AI Engineer").strip()
    
    paths = {
        "AI Engineer": {
            "title": "AI & Machine Learning Engineer Path",
            "stages": [
                {"stage": "1. Foundation", "description": "Master Python, Linear Algebra, Statistics & SQL", "type": "Skills"},
                {"stage": "2. Verified Course", "title": "DeepLearning.AI Machine Learning Specialization", "org": "DeepLearning.AI", "type": "Course"},
                {"stage": "3. Certification", "title": "IBM AI Engineering & Fundamentals", "org": "IBM", "type": "Certification"},
                {"stage": "4. Hackathon Practice", "title": "Kaggle Global ML Competitions / NASA Space Apps", "org": "Kaggle", "type": "Hackathon"},
                {"stage": "5. Career Outcome", "title": "Google Summer of Code / AI Research Internship", "org": "Google", "type": "Internship"}
            ]
        },
        "Full Stack Developer": {
            "title": "Full Stack Software Developer Path",
            "stages": [
                {"stage": "1. Foundation", "description": "Master HTML/CSS, JavaScript, Git & REST APIs", "type": "Skills"},
                {"stage": "2. Practice & Open Source", "title": "Hacktoberfest 2026", "org": "DigitalOcean & GitHub", "type": "Hackathon"},
                {"stage": "3. Verified Certification", "title": "SWAYAM & NPTEL Advanced Data Structures", "org": "NPTEL", "type": "Certification"},
                {"stage": "4. Hackathon Project", "title": "Chennai College Innovation Hackathon", "org": "IIT Madras", "type": "Hackathon"},
                {"stage": "5. Target Opportunity", "title": "Software Engineering Early Career Program", "org": "Google Careers", "type": "Job"}
            ]
        },
        "Cybersecurity Specialist": {
            "title": "Cybersecurity & Security Operations Path",
            "stages": [
                {"stage": "1. Foundation", "description": "Master Linux Commands, Networking Fundamentals & Python", "type": "Skills"},
                {"stage": "2. Industry Certificate", "title": "Google Cybersecurity Professional Certificate", "org": "Google", "type": "Certification"},
                {"stage": "3. Practice Sandbox", "title": "Cisco Networking Academy Security Training", "org": "Cisco", "type": "Course"},
                {"stage": "4. Cloud Security", "title": "Microsoft Azure Cloud Fundamentals (AZ-900)", "org": "Microsoft", "type": "Certification"},
                {"stage": "5. Career Outcome", "title": "Security Operations & Enterprise Cloud Internship", "org": "Microsoft", "type": "Job"}
            ]
        }
    }
    
    selected_path = paths.get(career_goal, paths["AI Engineer"])
    return jsonify(selected_path)


@app.route("/api/applications", methods=["GET", "POST", "DELETE"])
def applications_api():
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"message": "Sign in required to manage application tracker."}), 401
        
    conn = get_db()
    
    if request.method == "POST":
        data = request.get_json(force=True) or {}
        opp_id = data.get("opportunity_id")
        status = data.get("status", "saved").lower() # saved, applied, completed
        notes = data.get("notes", "")
        
        if not opp_id or status not in {"saved", "applied", "completed"}:
            conn.close()
            return jsonify({"message": "Invalid application status or opportunity ID."}), 400
            
        conn.execute(
            "INSERT INTO user_applications (user_id, opportunity_id, status, notes, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id, opportunity_id) DO UPDATE SET status=excluded.status, notes=excluded.notes, updated_at=CURRENT_TIMESTAMP",
            (user_id, opp_id, status, notes)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "app_status": status})
        
    if request.method == "DELETE":
        opp_id = request.args.get("opportunity_id")
        if opp_id:
            conn.execute("DELETE FROM user_applications WHERE user_id = ? AND opportunity_id = ?", (user_id, opp_id))
            conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Bookmark removed."})

    # GET request: return all applications with details
    rows = conn.execute(
        "SELECT a.status, a.notes, a.updated_at, o.* FROM user_applications a "
        "JOIN opportunities o ON a.opportunity_id = o.id WHERE a.user_id = ? ORDER BY a.updated_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    
    items = []
    saved_count = 0
    applied_count = 0
    completed_count = 0
    
    for r in rows:
        d = dict(r)
        d["registration_url"] = d.get("registration_url") or d.get("link") or ""
        d["trust_info"] = calculate_trust_score(d["registration_url"], d.get("source_verified"))
        st = d["status"]
        if st == "saved": saved_count += 1
        elif st == "applied": applied_count += 1
        elif st == "completed": completed_count += 1
        items.append(d)
        
    return jsonify({
        "metrics": {
            "saved": saved_count,
            "applied": applied_count,
            "completed": completed_count,
            "total": len(items)
        },
        "applications": items
    })


@app.route("/api/recommendations/<int:opportunity_id>/status", methods=["POST"])
def recommendation_status(opportunity_id):
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"message": "Sign in required."}), 401
    status = (request.get_json(force=True) or {}).get("status", "viewed")
    conn = get_db()
    conn.execute("UPDATE recommendation_history SET status = ? WHERE user_id = ? AND opportunity_id = ?", (status, user_id, opportunity_id))
    conn.commit()
    conn.close()
    return jsonify({"status": status})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)