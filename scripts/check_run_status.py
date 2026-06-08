import requests
import time

def check_run_status(run_id):
    url = f"http://95.163.223.186/api/runs/{run_id}"
    steps_url = f"http://95.163.223.186/api/steps/run/{run_id}"
    headers = {
        "Authorization": "Bearer ccae627d5f6a2f89ce49bc24f9d773b9"
    }
    
    print(f"Checking Run {run_id}...")
    r = requests.get(url, headers=headers)
    print(f"Run Status: {r.json().get('status')}")
    
    print("Checking Steps...")
    r = requests.get(steps_url, headers=headers)
    print(f"Raw Response: {r.text}")
    steps = r.json()
    if isinstance(steps, list):
        for s in steps:
            print(f"Step: {s.get('step_name')} | Status: {s.get('status')}")
    else:
        print(f"Unexpected response format: {type(steps)}")

if __name__ == "__main__":
    check_run_status(11)
