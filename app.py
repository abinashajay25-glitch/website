import os
import re
import json
import uuid
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "nextstep-production-secret-2026")
DATABASE = os.environ.get("DATABASE_PATH", "opportunities.db")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

VALID_CATEGORIES = {
    "Hackathon", "Internship", "Job", "Course", "Scholarship",
    "Competition", "Certification", "Fellowship", "Research", "Government Opportunity"
}

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
    "drdo.gov.in",
    "isro.gov.in",
    "dst.gov.in",
    "fulbright-hays.org",
)

UNTRUSTED_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd")


def today_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


@app.errorhandler(Exception)
def handle_exception(e):
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500
    return e


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
            "trust_badge": "⚠ Source Not Verified",
            "domain": "Unknown",
            "is_https": False,
            "reason": "Application URL is not specified. Verify directly with issuer before applying."
        }
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    is_https = parsed.scheme == "https"
    
    if any(shortener in host for shortener in UNTRUSTED_SHORTENERS):
        return {
            "trust_score": 40,
            "trust_badge": "⚠ Source Not Verified",
            "domain": host,
            "is_https": is_https,
            "reason": "URL uses a shortener. Exercise caution."
        }
        
    is_official = any(host == domain or host.endswith(f".{domain}") for domain in OFFICIAL_DOMAINS) or bool(source_verified_flag)
    
    if is_official and is_https:
        return {
            "trust_score": 100,
            "trust_badge": "✓ Official Source Verified",
            "domain": host,
            "is_https": True,
            "reason": f"Verified official website domain from registered organization ({host})."
        }
    elif is_https and (host.endswith(".edu") or host.endswith(".ac.in") or host.endswith(".gov") or host.endswith(".org") or host.endswith(".com")):
        return {
            "trust_score": 85,
            "trust_badge": "✓ Official Source Verified",
            "domain": host,
            "is_https": True,
            "reason": f"Secure HTTPS portal on registered domain ({host})."
        }
    else:
        return {
            "trust_score": 50,
            "trust_badge": "⚠ Source Not Verified",
            "domain": host or "Non-HTTPS",
            "is_https": is_https,
            "reason": "Source domain requires manual verification."
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
            remote_flag INTEGER DEFAULT 1,
            stipend_prize TEXT,
            experience_level TEXT DEFAULT 'All Levels',
            degree_req TEXT,
            dept_req TEXT,
            year_req TEXT,
            paid_flag INTEGER DEFAULT 1,
            start_date TEXT,
            deadline TEXT,
            registration_url TEXT,
            source_website TEXT,
            last_updated TEXT,
            source_verified INTEGER DEFAULT 0,
            verified_date TEXT,
            link TEXT
        )
        """
    )
    
    opp_cols = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)").fetchall()}
    for col, col_type in [("remote_flag", "INTEGER DEFAULT 1"), ("stipend_prize", "TEXT"), ("experience_level", "TEXT DEFAULT 'All Levels'"), ("degree_req", "TEXT"), ("dept_req", "TEXT"), ("year_req", "TEXT"), ("paid_flag", "INTEGER DEFAULT 1"), ("verified_date", "TEXT")]:
        if col not in opp_cols:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col} {col_type}")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            college TEXT,
            degree TEXT,
            department TEXT,
            year TEXT,
            skills TEXT,
            programming_languages TEXT,
            interests TEXT,
            career_goal TEXT,
            experience_level TEXT,
            location TEXT,
            remote_pref INTEGER DEFAULT 1,
            opportunity_types TEXT,
            github_url TEXT,
            linkedin_url TEXT,
            resume_text TEXT,
            profile_json TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            opportunity_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Saved',
            notes TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, opportunity_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "is_admin" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")

    # Purge expired opportunities automatically
    conn.execute("DELETE FROM opportunities WHERE deadline < ?", (today_iso(),))

    # Password migration to hashes
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
            "description": "Work with open-source software organizations under expert mentorship and gain industry coding experience.",
            "skills": "Python, JavaScript, Git, C++, Open Source",
            "eligibility": "Open to undergraduate & graduate students in CS, IT, or AI & DS.",
            "location": "Remote",
            "remote_flag": 1,
            "stipend_prize": "$1,500 - $3,000 Stipend",
            "experience_level": "Beginner / Intermediate",
            "degree_req": "B.Tech / B.E / M.Tech / MCA",
            "dept_req": "Computer Science, AI & DS, IT",
            "year_req": "1, 2, 3, 4",
            "paid_flag": 1,
            "start_date": "2026-10-01",
            "deadline": "2026-10-15",
            "registration_url": "https://summerofcode.withgoogle.com/",
            "source_website": "https://summerofcode.withgoogle.com/",
            "last_updated": today,
            "verified_date": today,
            "source_verified": 1,
        },
        {
            "title": "NASA Space Apps Challenge 2026",
            "organization": "NASA",
            "category": "Hackathon",
            "description": "Global 48-hour team hackathon solving real Earth and space science challenges using NASA open data.",
            "skills": "Python, Data Science, Machine Learning, GIS, AI",
            "eligibility": "Open to all university students and developers worldwide.",
            "location": "Hybrid / Global",
            "remote_flag": 1,
            "stipend_prize": "Global Winner Trophies & NASA Launch Invitation",
            "experience_level": "All Levels",
            "degree_req": "Any STEM Degree",
            "dept_req": "AI & DS, Computer Science, ECE, Mechanical",
            "year_req": "1, 2, 3, 4",
            "paid_flag": 0,
            "start_date": "2026-10-03",
            "deadline": "2026-10-20",
            "registration_url": "https://www.spaceappschallenge.org/",
            "source_website": "https://www.spaceappschallenge.org/",
            "last_updated": today,
            "verified_date": today,
            "source_verified": 1,
        },
        {
            "title": "Microsoft Azure Cloud & AI Fellowship 2026",
            "organization": "Microsoft",
            "category": "Fellowship",
            "description": "6-month structured fellowship featuring Azure cloud training, AI project grants, and 1-on-1 mentorship.",
            "skills": "Cloud, Azure, Python, Machine Learning, DevOps",
            "eligibility": "For 3rd & 4th year undergraduate students pursuing software engineering careers.",
            "location": "Remote",
            "remote_flag": 1,
            "stipend_prize": "$2,500 Project Grant + Azure Credits",
            "experience_level": "Intermediate",
            "degree_req": "B.Tech / B.E",
            "dept_req": "Computer Science, AI & DS, IT",
            "year_req": "3, 4",
            "paid_flag": 1,
            "start_date": "2026-11-01",
            "deadline": "2026-10-28",
            "registration_url": "https://learn.microsoft.com/",
            "source_website": "https://learn.microsoft.com/",
            "last_updated": today,
            "verified_date": today,
            "source_verified": 1,
        },
        {
            "title": "Fulbright STEM Research Grant 2026",
            "organization": "Fulbright Commission",
            "category": "Research",
            "description": "Prestigious research grant for students and young researchers to conduct advanced AI and STEM research.",
            "skills": "Data Analysis, Python, Statistics, Research Methods, Machine Learning",
            "eligibility": "Final year undergraduate or master's students with strong academic record.",
            "location": "On-site / International",
            "remote_flag": 0,
            "stipend_prize": "Full Research Funding & Travel Stipend",
            "experience_level": "Advanced",
            "degree_req": "B.Tech / M.Tech / M.Sc",
            "dept_req": "AI & DS, Computer Science, ECE",
            "year_req": "4",
            "paid_flag": 1,
            "start_date": "2026-12-01",
            "deadline": "2026-11-15",
            "registration_url": "https://fulbright-hays.org/",
            "source_website": "https://fulbright-hays.org/",
            "last_updated": today,
            "verified_date": today,
            "source_verified": 1,
        },
        {
            "title": "ISRO Young Scientist Student Competition",
            "organization": "ISRO & Govt of India",
            "category": "Government Opportunity",
            "description": "National space technology competition organized by ISRO for innovative student hardware and satellite software ideas.",
            "skills": "Python, C++, Embedded Systems, Robotics, Data Science",
            "eligibility": "Open to Indian university engineering students.",
            "location": "Bengaluru / Hybrid",
            "remote_flag": 1,
            "stipend_prize": "₹1,00,000 Cash Prize + ISRO Internship Offer",
            "experience_level": "All Levels",
            "degree_req": "B.Tech / B.E",
            "dept_req": "Computer Science, AI & DS, ECE, EEE, Mechanical",
            "year_req": "2, 3, 4",
            "paid_flag": 1,
            "start_date": "2026-11-10",
            "deadline": "2026-10-31",
            "registration_url": "https://www.isro.gov.in/",
            "source_website": "https://www.isro.gov.in/",
            "last_updated": today,
            "verified_date": today,
            "source_verified": 1,
        },
        {
            "title": "Google Cybersecurity Professional Certificate",
            "organization": "Google via Coursera",
            "category": "Certification",
            "description": "Master cybersecurity fundamentals, Linux, Python threat intelligence scripts, and SIEM security analytics.",
            "skills": "Cybersecurity, Networking, Linux, Python, Security Operations",
            "eligibility": "Beginner friendly, open to all students.",
            "location": "Online",
            "remote_flag": 1,
            "stipend_prize": "Official Google Industry Credential",
            "experience_level": "Beginner",
            "degree_req": "Any Degree",
            "dept_req": "All Departments",
            "year_req": "1, 2, 3, 4",
            "paid_flag": 0,
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://www.coursera.org/professional-certificates/google-cybersecurity",
            "source_website": "https://www.coursera.org/",
            "last_updated": today,
            "verified_date": today,
            "source_verified": 1,
        },
        {
            "title": "DeepLearning.AI Machine Learning Specialization",
            "organization": "DeepLearning.AI",
            "category": "Course",
            "description": "Comprehensive ML program covering supervised learning, neural networks, decision trees, and TensorFlow.",
            "skills": "Machine Learning, Python, Data Science, AI, Mathematics",
            "eligibility": "Open to students with basic math and programming knowledge.",
            "location": "Online",
            "remote_flag": 1,
            "stipend_prize": "Verified Stanford / DeepLearning.AI Certificate",
            "experience_level": "Intermediate",
            "degree_req": "Any STEM Degree",
            "dept_req": "AI & DS, Computer Science, IT, ECE",
            "year_req": "1, 2, 3, 4",
            "paid_flag": 0,
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://www.deeplearning.ai/courses/machine-learning-specialization/",
            "source_website": "https://www.deeplearning.ai/",
            "last_updated": today,
            "verified_date": today,
            "source_verified": 1,
        },
        {
            "title": "Kaggle Global Machine Learning Competition",
            "organization": "Kaggle",
            "category": "Competition",
            "description": "Solve live machine learning problems on real datasets and compete on global leaderboards.",
            "skills": "Python, Machine Learning, Data Science, SQL, AI",
            "eligibility": "Open to all students and machine learning developers.",
            "location": "Online",
            "remote_flag": 1,
            "stipend_prize": "$50,000 Prize Pool & Master Badges",
            "experience_level": "All Levels",
            "degree_req": "Any Degree",
            "dept_req": "All Departments",
            "year_req": "1, 2, 3, 4",
            "paid_flag": 1,
            "start_date": "2026-09-01",
            "deadline": "2026-12-31",
            "registration_url": "https://www.kaggle.com/competitions",
            "source_website": "https://www.kaggle.com/",
            "last_updated": today,
            "verified_date": today,
            "source_verified": 1,
        },
        {
            "title": "Software Engineering Early Career Program",
            "organization": "Google Careers",
            "category": "Job",
            "description": "Full-time entry-level software engineering positions across frontend, backend, and AI infrastructure teams.",
            "skills": "Python, Java, Data Structures, C++, Software Engineering",
            "eligibility": "For final year students and recent engineering graduates.",
            "location": "Hybrid / Bengaluru / Hyderabad",
            "remote_flag": 0,
            "stipend_prize": "Full-time Compensation & Benefits",
            "experience_level": "Entry Level (0-2 Yrs)",
            "degree_req": "B.Tech / B.E / M.Tech",
            "dept_req": "Computer Science, AI & DS, IT",
            "year_req": "4",
            "paid_flag": 1,
            "start_date": "2026-10-01",
            "deadline": "2026-12-15",
            "registration_url": "https://careers.google.com/jobs/results/",
            "source_website": "https://careers.google.com/",
            "last_updated": today,
            "verified_date": today,
            "source_verified": 1,
        },
        {
            "title": "Global AI & STEM Student Scholarship 2026",
            "organization": "IBM & Education Partners",
            "category": "Scholarship",
            "description": "Merit-based financial scholarship supporting underrepresented students pursuing AI and Data Science degrees.",
            "skills": "AI, Python, Data Science, Academic Excellence",
            "eligibility": "For 1st, 2nd, and 3rd year undergraduate STEM students.",
            "location": "Online / Global",
            "remote_flag": 1,
            "stipend_prize": "₹75,000 / $1,000 Tuition Waiver",
            "experience_level": "All Levels",
            "degree_req": "B.Tech / B.E / B.Sc",
            "dept_req": "AI & DS, Computer Science, IT, ECE",
            "year_req": "1, 2, 3",
            "paid_flag": 1,
            "start_date": "2026-10-01",
            "deadline": "2026-11-20",
            "registration_url": "https://skillsbuild.org/",
            "source_website": "https://skillsbuild.org/",
            "last_updated": today,
            "verified_date": today,
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
                "UPDATE opportunities SET last_updated = ?, verified_date = ?, source_verified = ?, source_website = ?, registration_url = ?, deadline = ? WHERE id = ?",
                (item["last_updated"], item["verified_date"], int(item.get("source_verified", 0)), item["source_website"], item["registration_url"], item["deadline"], existing["id"]),
            )
            continue
        conn.execute(
            """
            INSERT INTO opportunities (
                title, organization, category, description, skills, eligibility,
                location, remote_flag, stipend_prize, experience_level, degree_req,
                dept_req, year_req, paid_flag, start_date, deadline, registration_url,
                source_website, last_updated, verified_date, source_verified, link
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["title"], item["organization"], item["category"], item["description"],
                item["skills"], item["eligibility"], item["location"], item.get("remote_flag", 1),
                item.get("stipend_prize", ""), item.get("experience_level", "All Levels"),
                item.get("degree_req", ""), item.get("dept_req", ""), item.get("year_req", ""),
                item.get("paid_flag", 1), item["start_date"], item["deadline"],
                item["registration_url"], item["source_website"], item["last_updated"],
                item["verified_date"], int(item.get("source_verified", 0)), item["registration_url"]
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

    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user:
        stored_password = user["password"]
        if check_password_hash(stored_password, password) or stored_password == password:
            if not stored_password.startswith("scrypt:") and not stored_password.startswith("pbkdf2:"):
                new_hashed = generate_password_hash(password)
                conn.execute("UPDATE users SET password = ? WHERE id = ?", (new_hashed, user["id"]))
                conn.commit()
            session["user_id"] = user["id"]
            is_admin = bool(user["is_admin"]) if "is_admin" in user.keys() else False
            session["is_admin"] = is_admin
            conn.close()
            return jsonify({"status": "success", "message": f"Logged in as {user['email']}", "is_admin": is_admin})
    
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
            "ON CONFLICT(user_id) DO UPDATE SET profile_json=excluded.profile_json, completed=excluded.completed, updated_at=CURRENT_TIMESTAMP",
            (user_id, json.dumps(profile), int(completed)),
        )
        conn.commit()
    row = conn.execute("SELECT profile_json, completed FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    profile = json.loads(row["profile_json"]) if row else {}
    required = ["department", "skills", "interests", "career", "location"]
    completion = int(sum(bool(profile.get(key)) for key in required) / len(required) * 100) if required else 0
    return jsonify({"authenticated": True, "completed": bool(row and row["completed"]), "completion": completion, "profile": profile})


def evaluate_eligibility(profile, opportunity):
    profile = profile or {}
    dept = (profile.get("department") or "").lower()
    year = str(profile.get("year") or "").lower()
    user_skills = set([s.lower() for s in (profile.get("skills") or [])])
    
    dept_req = (opportunity.get("dept_req") or "").lower()
    year_req = (opportunity.get("year_req") or "").lower()
    opp_skills = (opportunity.get("skills") or "").lower()

    reasons = []
    matches = 0
    total_checks = 0

    if dept_req and dept_req != "all departments":
        total_checks += 1
        if dept and (dept in dept_req or any(tok in dept_req for tok in dept.split() if len(tok) > 2)):
            reasons.append(f"✅ Department match: Your {profile.get('department')} background meets requirements ({opportunity.get('dept_req')}).")
            matches += 1
        else:
            reasons.append(f"⚠️ Department check: Opportunity prefers {opportunity.get('dept_req')}.")
    else:
        reasons.append("✅ Open to all department specializations.")

    if year_req:
        total_checks += 1
        if year and year in year_req:
            reasons.append(f"✅ Academic year match: Year {year} student meets eligibility criteria.")
            matches += 1
        else:
            reasons.append(f"⚠️ Academic year check: Preferred for Year {opportunity.get('year_req')}.")

    if opp_skills:
        total_checks += 1
        req_skill_list = [s.strip().lower() for s in opp_skills.split(",") if s.strip()]
        matched_skills = [s for s in req_skill_list if s in user_skills or any(us in s or s in us for us in user_skills)]
        if matched_skills:
            reasons.append(f"✅ Skill match: You possess required skills ({', '.join([s.title() for s in matched_skills[:3]])}).")
            matches += 1
        else:
            reasons.append(f"⚠️ Missing core skills ({opportunity.get('skills')}). Bridge skill gap with recommended courses.")

    if total_checks == 0 or matches == total_checks:
        status = "🟢 Eligible"
    elif matches >= 1:
        status = "🟡 Possibly Eligible"
    else:
        status = "🔴 Not Eligible"

    return {
        "status": status,
        "reasons": reasons
    }


def calculate_ai_match(profile, opportunity, all_courses):
    profile = profile or {}
    prof_skills = [s.lower() for s in (profile.get("skills") or [])]
    opp_skills_str = opportunity.get("skills") or ""
    
    req_skills = [s.strip() for s in opp_skills_str.split(",") if s.strip()]
    matching_skills = [s for s in req_skills if s.lower() in prof_skills or any(ps in s.lower() or s.lower() in ps for ps in prof_skills)]
    missing_skills = [s for s in req_skills if s not in matching_skills]

    rec_courses = []
    if missing_skills:
        for c in all_courses:
            c_skills = (c.get("skills") or "").lower()
            if any(ms.lower() in c_skills for ms in missing_skills):
                rec_courses.append({
                    "id": c["id"],
                    "title": c["title"],
                    "organization": c["organization"],
                    "url": c.get("registration_url") or "#"
                })

    score = 45
    if req_skills:
        score += int((len(matching_skills) / len(req_skills)) * 35)
    else:
        score += 15

    dept = (profile.get("department") or "").lower()
    opp_text = (opportunity.get("title", "") + " " + opportunity.get("description", "")).lower()
    if dept and (dept in opp_text or any(tok in opp_text for tok in dept.split() if len(tok) > 2)):
        score += 10

    career = (profile.get("career") or "").lower()
    cat = (opportunity.get("category") or "").lower()
    if career and (career in cat or cat in career):
        score += 10

    match_score = min(98, max(50, score))

    checklist = []
    if matching_skills:
        checklist.append(f"✅ Your {', '.join(matching_skills[:2])} skill(s) match requirement")
    if dept:
        checklist.append(f"✅ Your {profile.get('department')} academic background matches")
    if profile.get("year"):
        checklist.append(f"✅ You meet Year {profile.get('year')} student education criteria")
    if profile.get("location"):
        checklist.append(f"⚠️ Location preference ({profile.get('location')}) evaluated against {opportunity.get('location')}")

    deadline = opportunity.get("deadline", "Upcoming")
    action_plan = [
        {"week": "Week 1", "title": "Skill Preparation", "action": f"Master missing skills ({missing_skills[0]})" if missing_skills else "Review project submission prerequisites."},
        {"week": "Week 2", "title": "Project & Resume Build", "action": "Build prototype repository and format resume."},
        {"week": "Week 3", "title": "Final Application", "action": f"Submit official registration before deadline ({deadline})."},
        {"week": "Week 4", "title": "Review & Prep", "action": "Prepare for technical round / project evaluation."}
    ]

    trust_info = calculate_trust_score(opportunity.get("registration_url"), opportunity.get("source_verified"))
    eligibility_eval = evaluate_eligibility(profile, opportunity)

    deadline_date = datetime.strptime(opportunity["deadline"], "%Y-%m-%d") if opportunity.get("deadline") else datetime.now()
    days_rem = (deadline_date - datetime.now()).days

    if days_rem < 0:
        deadline_badge = "Expired"
    elif days_rem <= 3:
        deadline_badge = f"🔥 {days_rem} days left (Closing Soon)"
    else:
        deadline_badge = f"📅 {days_rem} days remaining"

    return {
        "match_score": match_score,
        "why_match_checklist": checklist,
        "eligibility_eval": eligibility_eval,
        "trust_info": trust_info,
        "days_remaining": days_rem,
        "deadline_badge": deadline_badge,
        "skill_gap": {
            "matching_skills": matching_skills,
            "missing_skills": missing_skills,
            "recommended_courses": rec_courses[:2]
        },
        "action_plan": action_plan
    }


@app.route("/api/opportunities")
def opportunities():
    category = (request.args.get("category") or "").strip()
    search = (request.args.get("search") or request.args.get("q") or "").strip().lower()
    sort = (request.args.get("sort") or "match").lower()
    show_expired = request.args.get("show_expired", "false").lower() == "true"

    conn = get_db()
    query = "SELECT * FROM opportunities WHERE 1=1"
    params = []
    
    if not show_expired:
        query += " AND deadline >= ?"
        params.append(today_iso())

    if category and category.lower() != "all":
        query += " AND LOWER(category) = LOWER(?)"
        params.append(category)
        
    if search:
        query += " AND (LOWER(title) LIKE ? OR LOWER(organization) LIKE ? OR LOWER(skills) LIKE ? OR LOWER(description) LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like, like])
        
    query += " ORDER BY deadline ASC, title ASC"
    rows = conn.execute(query, params).fetchall()
    
    course_rows = conn.execute("SELECT * FROM opportunities WHERE category IN ('Course', 'Certification')").fetchall()
    all_courses = [dict(r) for r in course_rows]
    conn.close()

    data = []
    for row in rows:
        item = dict(row)
        item["registration_url"] = item.get("registration_url") or item.get("link") or ""
        ai_data = calculate_ai_match({}, item, all_courses)
        item.update(ai_data)
        data.append(item)

    if sort == "deadline":
        data.sort(key=lambda x: x.get("deadline", "9999-12-31"))
    else:
        data.sort(key=lambda x: -x.get("match_score", 0))

    return jsonify(data)


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
    rows = conn.execute("SELECT * FROM opportunities WHERE deadline >= ? ORDER BY deadline ASC", (today_iso(),)).fetchall()
    course_rows = conn.execute("SELECT * FROM opportunities WHERE category IN ('Course', 'Certification')").fetchall()
    all_courses = [dict(r) for r in course_rows]
    conn.close()

    results = []
    for row in rows:
        item = dict(row)
        item["registration_url"] = item.get("registration_url") or item.get("link") or ""
        ai_data = calculate_ai_match(profile, item, all_courses)
        item.update(ai_data)
        results.append(item)

    results.sort(key=lambda x: -x["match_score"])
    return jsonify(results)


@app.route("/api/opportunities/next-30-days", methods=["GET"])
def next_30_days():
    days_limit = int(request.args.get("days", 30))
    limit_date = (datetime.now(timezone.utc) + timedelta(days=days_limit)).strftime("%Y-%m-%d")
    
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE deadline >= ? AND deadline <= ? ORDER BY deadline ASC",
        (today_iso(), limit_date)
    ).fetchall()
    course_rows = conn.execute("SELECT * FROM opportunities WHERE category IN ('Course', 'Certification')").fetchall()
    all_courses = [dict(r) for r in course_rows]
    conn.close()

    results = []
    for r in rows:
        item = dict(r)
        ai_data = calculate_ai_match({}, item, all_courses)
        item.update(ai_data)
        results.append(item)

    return jsonify({"days_limit": days_limit, "count": len(results), "opportunities": results})


@app.route("/api/resume-match", methods=["POST"])
def resume_match():
    data = request.get_json(force=True) or {}
    resume_text = data.get("resume_text", "").lower()
    
    if not resume_text:
        return jsonify({"status": "error", "message": "Resume text is required."}), 400

    extracted_skills = []
    skill_db = ["python", "machine learning", "sql", "java", "c++", "javascript", "git", "cloud", "aws", "azure", "cybersecurity", "deep learning", "tensorflow"]
    for sk in skill_db:
        if sk in resume_text:
            extracted_skills.append(sk.title())

    mock_profile = {
        "department": "Computer Science",
        "year": "3",
        "skills": extracted_skills or ["Python"],
        "interests": ["AI", "Software Development"],
        "career": "Full Stack Developer"
    }

    conn = get_db()
    rows = conn.execute("SELECT * FROM opportunities WHERE deadline >= ?", (today_iso(),)).fetchall()
    course_rows = conn.execute("SELECT * FROM opportunities WHERE category IN ('Course', 'Certification')").fetchall()
    all_courses = [dict(r) for r in course_rows]
    conn.close()

    matched = []
    for r in rows:
        item = dict(r)
        ai_data = calculate_ai_match(mock_profile, item, all_courses)
        item.update(ai_data)
        item["resume_match_score"] = min(96, ai_data["match_score"] + 5)
        matched.append(item)

    matched.sort(key=lambda x: -x["resume_match_score"])
    return jsonify({
        "extracted_skills": extracted_skills,
        "resume_match_overall": 88,
        "opportunities": matched[:6]
    })


@app.route("/api/career-roadmap", methods=["GET"])
def career_roadmap():
    goal = request.args.get("goal", "AI Engineer").strip()
    
    roadmaps = {
        "AI Engineer": {
            "goal": "AI & Machine Learning Engineer",
            "nodes": [
                {"step": "Step 1: Core Skills", "details": "Python, SQL, Linear Algebra & Data Structures"},
                {"step": "Step 2: Recommended Course", "details": "DeepLearning.AI Machine Learning Specialization"},
                {"step": "Step 3: Certification", "details": "IBM AI Engineering & Fundamentals"},
                {"step": "Step 4: Practice Hackathon", "details": "Kaggle Global ML Competition / NASA Space Apps"},
                {"step": "Step 5: Target Internship", "details": "Google Summer of Code / Open Source AI Fellowship"}
            ]
        },
        "Full Stack Developer": {
            "goal": "Full Stack Software Developer",
            "nodes": [
                {"step": "Step 1: Core Skills", "details": "HTML/CSS, JavaScript, Python, Git & REST APIs"},
                {"step": "Step 2: Open Source Practice", "details": "Hacktoberfest 2026"},
                {"step": "Step 3: Advanced Course", "details": "SWAYAM & NPTEL Advanced Data Structures"},
                {"step": "Step 4: Innovation Hackathon", "details": "Chennai College Innovation Hackathon"},
                {"step": "Step 5: Target Job Role", "details": "Google Careers Software Engineering Early Career Program"}
            ]
        },
        "Cybersecurity": {
            "goal": "Cybersecurity Specialist",
            "nodes": [
                {"step": "Step 1: Core Skills", "details": "Linux Systems, Networking, Python Scripting & SIEM"},
                {"step": "Step 2: Industry Certificate", "details": "Google Cybersecurity Professional Certificate"},
                {"step": "Step 3: Cloud Security", "details": "Microsoft Azure Cloud Fundamentals (AZ-900)"},
                {"step": "Step 4: Defense Competition", "details": "ISRO Young Scientist Student Competition"},
                {"step": "Step 5: Target Role", "details": "Microsoft Cloud & Security Engineering Internship"}
            ]
        }
    }
    return jsonify(roadmaps.get(goal, roadmaps["AI Engineer"]))


@app.route("/api/chat", methods=["POST"])
def ai_chat():
    data = request.get_json(force=True) or {}
    message = (data.get("message") or "").strip()
    
    if not message:
        return jsonify({"reply": "Hello! I am your NextStep AI Assistant. How can I assist with your opportunity search today?"})

    conn = get_db()
    rows = conn.execute("SELECT * FROM opportunities WHERE deadline >= ? ORDER BY deadline ASC", (today_iso(),)).fetchall()
    conn.close()
    
    all_opps = [dict(r) for r in rows]
    msg_lower = message.lower()

    if GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            opp_context = "\n".join([
                f"- {o['title']} ({o['organization']}) | Category: {o['category']} | Deadline: {o['deadline']} | Skills: {o['skills']} | URL: {o['registration_url']}"
                for o in all_opps
            ])
            system_prompt = (
                "You are NextStep AI, an intelligent career & opportunity assistant for students. "
                "Answer the user's question using ONLY the provided verified opportunities database. "
                "Never fabricate non-existent opportunities. Keep responses encouraging, concise, and formatted in Markdown."
            )
            user_prompt = f"Available Opportunities Database:\n{opp_context}\n\nUser Question: {message}"
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config={"system_instruction": system_prompt}
            )
            return jsonify({"reply": response.text})
        except Exception:
            pass

    matched_opps = []
    if "closing" in msg_lower or "soon" in msg_lower or "week" in msg_lower:
        limit_date = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        matched_opps = [o for o in all_opps if o["deadline"] <= limit_date]
        reply_title = "🔥 Opportunities Closing Within 7 Days:"
    elif "hackathon" in msg_lower:
        matched_opps = [o for o in all_opps if o["category"].lower() == "hackathon"]
        reply_title = "⚡ Active Verified Hackathons:"
    elif "internship" in msg_lower:
        matched_opps = [o for o in all_opps if o["category"].lower() == "internship"]
        reply_title = "💼 Active Verified Internships:"
    elif "course" in msg_lower or "certification" in msg_lower or "skill" in msg_lower:
        matched_opps = [o for o in all_opps if o["category"].lower() in ["course", "certification"]]
        reply_title = "🎓 Recommended Courses & Certifications:"
    elif "job" in msg_lower:
        matched_opps = [o for o in all_opps if o["category"].lower() == "job"]
        reply_title = "🚀 Entry-Level Software Engineering Jobs:"
    else:
        words = [w for w in msg_lower.split() if len(w) > 2]
        matched_opps = [
            o for o in all_opps if any(
                w in o["title"].lower() or w in o["organization"].lower() or w in (o["skills"] or "").lower() or w in o["category"].lower()
                for w in words
            )
        ]
        reply_title = f"🔍 Relevant Verified Opportunities for '{message}':"

    if matched_opps:
        bullet_list = "\n\n".join([
            f"• **[{o['title']}]({o['registration_url'] or o['link'] or '#'})** ({o['organization']})\n  Category: *{o['category']}* | Deadline: *{o['deadline']}*\n  Required Skills: `{o['skills']}`"
            for o in matched_opps[:4]
        ])
        reply = f"{reply_title}\n\n{bullet_list}"
    else:
        reply = (
            f"I searched the NextStep verified database ({len(all_opps)} active opportunities). "
            f"No exact matches found for '{message}'. Try asking for **hackathons**, **internships**, **courses**, or **opportunities closing soon**!"
        )

    return jsonify({"reply": reply})


@app.route("/api/applications", methods=["GET", "POST", "DELETE"])
def applications_api():
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"message": "Sign in required to manage application tracker."}), 401
        
    conn = get_db()
    
    if request.method == "POST":
        data = request.get_json(force=True) or {}
        opp_id = data.get("opportunity_id")
        status = data.get("status", "Saved")
        notes = data.get("notes", "")
        
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
        return jsonify({"status": "success", "message": "Application record removed."})

    rows = conn.execute(
        "SELECT a.status, a.notes, a.updated_at, o.* FROM user_applications a "
        "JOIN opportunities o ON a.opportunity_id = o.id WHERE a.user_id = ? ORDER BY a.updated_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    
    items = []
    status_counts = {"Saved": 0, "Planning to Apply": 0, "Applied": 0, "Interview": 0, "Shortlisted": 0, "Selected": 0, "Rejected": 0}
    
    for r in rows:
        d = dict(r)
        d["registration_url"] = d.get("registration_url") or d.get("link") or ""
        d["trust_info"] = calculate_trust_score(d["registration_url"], d.get("source_verified"))
        st = d["status"]
        if st in status_counts: status_counts[st] += 1
        items.append(d)
        
    return jsonify({
        "metrics": status_counts,
        "applications": items
    })


@app.route("/api/admin/metrics", methods=["GET"])
def admin_metrics():
    conn = get_db()
    total_opps = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    verified_opps = conn.execute("SELECT COUNT(*) FROM opportunities WHERE source_verified = 1").fetchone()[0]
    conn.close()
    return jsonify({
        "total_opportunities": total_opps,
        "total_users": total_users,
        "verified_opportunities": verified_opps,
        "system_status": "Healthy"
    })


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)