import requests

def check_results(run_id):
    headers = {
        "Authorization": "Bearer ccae627d5f6a2f89ce49bc24f9d773b9"
    }
    
    # 1. Check Run Status
    r = requests.get(f"http://95.163.223.186/api/runs/{run_id}", headers=headers)
    run = r.json()
    print(f"Run {run_id} Status: {run.get('status')}")
    print(f"Master Email Body Sample: {run.get('master_email_body')[:200] if run.get('master_email_body') else 'N/A'}...")

    # 2. Check Drafts
    # We need to find contacts first or just list drafts for the run
    # There is likely an endpoint for drafts by run
    drafts_url = f"http://95.163.223.186/api/email-drafts/run/{run_id}"
    r = requests.get(drafts_url, headers=headers)
    if r.status_code == 200:
        drafts = r.json()
        print(f"\nFound {len(drafts)} email drafts.")
        for d in drafts[:3]:
            print(f"\n--- Draft ID: {d.get('id')} ---")
            print(f"Full Draft Data: {d}")
    else:
        print(f"\nFailed to fetch drafts: {r.status_code} {r.text}")

if __name__ == "__main__":
    check_results(11)
