import os
import json
import unittest

os.environ["DATABASE_PATH"] = "test_opportunities.db"

import app

class TestNextStepHackathonUpgrade(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.init_db()

    def setUp(self):
        self.client = app.app.test_client()

    def test_01_eligibility_evaluation(self):
        """Verify deterministic eligibility evaluation status"""
        profile = {"department": "AI & Data Science", "year": "2", "skills": ["Python", "SQL"]}
        opp = {
            "dept_req": "AI & Data Science",
            "year_req": "1, 2, 3",
            "skills": "Python, Machine Learning"
        }
        elig = app.evaluate_eligibility(profile, opp)
        self.assertIn("Eligible", elig["status"])

    def test_02_trust_score(self):
        """Verify official source verification parser"""
        v1 = app.calculate_trust_score("https://summerofcode.withgoogle.com/")
        self.assertIn("Official Source Verified", v1["trust_badge"])

    def test_03_next_30_days_api(self):
        """Verify Next 30 Days API filter"""
        res = self.client.get('/api/opportunities/next-30-days?days=30')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("count", data)

    def test_04_resume_match_api(self):
        """Verify Resume Skill Parser API"""
        res = self.client.post('/api/resume-match', json={
            'resume_text': "Software Engineer student proficient in Python, SQL, Machine Learning, and Git."
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("Python", data["extracted_skills"])

    def test_05_career_roadmap_api(self):
        """Verify AI Career Roadmap API"""
        res = self.client.get('/api/career-roadmap?goal=AI%20Engineer')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(len(data["nodes"]), 5)

    def test_06_ai_chat_assistant(self):
        """Verify NextStep AI Career Chat Assistant API"""
        res = self.client.post('/api/chat', json={'message': 'Find active AI hackathons for me'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("Hackathons", data["reply"])

    def test_07_admin_metrics(self):
        """Verify Admin Metrics Endpoint"""
        res = self.client.get('/api/admin/metrics')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertGreater(data["total_opportunities"], 0)

if __name__ == '__main__':
    unittest.main()
