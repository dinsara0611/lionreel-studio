import unittest
import urllib.request
import json

class TestFix6Backend(unittest.TestCase):
    def test_status_endpoint_returns_audit_and_elapsed(self):
        url = "http://localhost:8000/api/status"
        req = urllib.request.urlopen(url)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        
        self.assertIn("candidateReports", data)
        self.assertIn("elapsedSeconds", data)
        self.assertIn("status", data)
        print(f"Status: {data['status']}, Candidate reports count: {len(data['candidateReports'])}, Elapsed: {data['elapsedSeconds']}s")

    def test_logs_endpoint_monotonic_seq(self):
        # Test logs endpoint with dummy or current job
        url = "http://localhost:8000/api/logs"
        req = urllib.request.urlopen(url)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        
        self.assertIn("logs", data)
        self.assertIn("last_seq", data)
        self.assertIn("lines", data)
        print(f"Logs response: {len(data['lines'])} lines, last_seq={data['last_seq']}")

if __name__ == "__main__":
    unittest.main()
