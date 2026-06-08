import requests

def run_generate_emails(run_id):
    url = f"http://95.163.223.186/api/steps/run/{run_id}/execute/generate_emails"
    headers = {
        "Authorization": "Bearer ccae627d5f6a2f89ce49bc24f9d773b9"
    }
    print(f"Triggering email generation for Run {run_id}...")
    r = requests.post(url, headers=headers, timeout=300)
    print(f"Status Code: {r.status_code}")
    print(r.text)

if __name__ == "__main__":
    run_generate_emails(11)
