import os
import json
import unittest
from datetime import datetime, timedelta, timezone

# Ensure local test db
os.environ["DATABASE_PATH"] = "test_opportunities.db"

import app

class TestNextStepDecisionEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.init_db()

    def setUp(self):
        self.client = app.app.test_client()

    def test_01_password_security(self):
        """Verify passwords are hashed and secure"""
        email = "teststudent@university.edu"
        password = "SecurePassword123"
        
        # Test Signup
        res = self.client.post('/api/auth', json={'action': 'signup', 'email': email, 'password': password})
        self.assertEqual(res.status_code, 200)
        
        # Verify in DB that stored password is hashed (scrypt or pbkdf2)
        conn = app.get_db()
        user = conn.execute("SELECT password FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        self.assertTrue(user['password'].startswith('scrypt:') or user['password'].startswith('pbkdf2:'))

    def test_02_trust_score(self):
        """Verify trust calculation (Verified, Partially Verified, Unverified)"""
        v1 = app.calculate_trust_score("https://summerofcode.withgoogle.com/")
        self.assertEqual(v1["trust_badge"], "Verified")
        self.assertEqual(v1["trust_score"], 100)
        
        v2 = app.calculate_trust_score("https://mycollege.edu/hackathon")
        self.assertEqual(v2["trust_badge"], "Partially Verified")
        
        v3 = app.calculate_trust_score("http://bit.ly/fake-link")
        self.assertEqual(v3["trust_badge"], "Unverified")

    def test_03_skill_gap_analysis(self):
        """Verify skill gap detection and course recommendations"""
        profile_skills = ["Python", "Git"]
        opp_skills = "Python, Machine Learning, TensorFlow, Git"
        all_courses = [
            {"id": 1, "title": "DeepLearning.AI ML Specialization", "organization": "DeepLearning.AI", "skills": "Machine Learning, Python, TensorFlow", "registration_url": "https://www.deeplearning.ai/"}
        ]
        gap = app.analyze_skill_gap(profile_skills, opp_skills, all_courses)
        self.assertIn("Python", gap["matching_skills"])
        self.assertIn("Machine Learning", gap["missing_skills"])
        self.assertEqual(len(gap["recommended_courses"]), 1)

    def test_04_nlp_search_api(self):
        """Verify natural language search intent extraction"""
        res = self.client.post('/api/nlp-search', json={
            'query': "I'm a 2nd year AI & DS student with Python and ML. Find free AI hackathons for me."
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["intent"]["detected_category"], "Hackathon")
        self.assertIn("Python", data["intent"]["detected_skills"])

    def test_05_learning_path_api(self):
        """Verify personalized learning path generation"""
        res = self.client.get('/api/learning-path?goal=AI%20Engineer')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("AI", data["title"])
        self.assertEqual(len(data["stages"]), 5)

if __name__ == '__main__':
    unittest.main()
