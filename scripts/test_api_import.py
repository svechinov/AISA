import requests
import os

def test_import():
    url = "http://95.163.223.186/api/runs/import-amocrm"
    data = {
        "run_name": "E2E Test 29.05 Script",
        "project_id": 1
    }
    file_path = "test_leads.xlsx"
    headers = {
        "Authorization": f"Bearer {os.environ.get('GLOBAL_PASSWORD', '')}"
    }
    
    with open(file_path, "rb") as f:
        files = {
            "file": (file_path, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        }
        print(f"Sending POST to {url}...")
        try:
            r = requests.post(url, data=data, files=files, headers=headers, timeout=60)
            print(f"Status Code: {r.status_code}")
            print("Response:")
            print(r.text)
        except Exception as e:
            print(f"Request failed: {e}")

if __name__ == "__main__":
    test_import()
