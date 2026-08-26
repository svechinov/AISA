import os
import requests

VDS_HOST = os.environ.get("VDS_HOST", "<your-server-ip>")

def check_contacts(run_id):
    headers = {
        "Authorization": f"Bearer {os.environ.get('GLOBAL_PASSWORD', '')}"
    }

    url = f"http://{VDS_HOST}/api/runs/{run_id}/companies"
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        contacts = data.get("contacts", [])
        print(f"Found {len(contacts)} contacts for Run {run_id}:")
        for c in contacts:
            print(f"ID: {c.get('id')} | Name: {c.get('name')} | Review Status: {c.get('review_status')} | Status: {c.get('status')}")
    else:
        print(f"Failed to fetch contacts: {r.status_code} {r.text}")

if __name__ == "__main__":
    check_contacts(11)
