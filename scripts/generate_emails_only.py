import os
import requests

VDS_HOST = os.environ.get("VDS_HOST", "<your-server-ip>")

def run_generate_emails(run_id):
    url = f"http://{VDS_HOST}/api/steps/run/{run_id}/execute/generate_emails"
    headers = {
        "Authorization": f"Bearer {os.environ.get('GLOBAL_PASSWORD', '')}"
    }
    print(f"Triggering email generation for Run {run_id}...")
    r = requests.post(url, headers=headers, timeout=300)
    print(f"Status Code: {r.status_code}")
    print(r.text)

if __name__ == "__main__":
    run_generate_emails(11)
