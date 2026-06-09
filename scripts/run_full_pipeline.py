import os
import requests
import sys

def execute_step(run_id, step_name):
    url = f"http://95.163.223.186/api/steps/run/{run_id}/execute/{step_name}"
    headers = {
        "Authorization": f"Bearer {os.environ.get('GLOBAL_PASSWORD', '')}"
    }
    print(f"Executing step '{step_name}' for Run {run_id}...")
    try:
        r = requests.post(url, headers=headers, timeout=300)
        print(f"Status Code: {r.status_code}")
        print("Response:")
        print(r.text)
        return r.status_code == 200
    except Exception as e:
        print(f"Request failed: {e}")
        return False

if __name__ == "__main__":
    # 1. Enrich CRM Data (OSINT via Tavily)
    if execute_step(11, "enrich_crm_data"):
        print("\nOSINT Enrichment completed successfully.")
        
        # 2. Validate Contacts
        if execute_step(11, "validate_contacts"):
            print("\nContacts validation completed.")
            
            # 3. Generate Master Email Draft
            if execute_step(11, "generate_master_email_draft"):
                print("\nMaster Email Draft generated.")
                
                # 4. Generate Final Emails
                if execute_step(11, "generate_emails"):
                    print("\nFinal Emails generation triggered.")
                else:
                    print("\nFailed to trigger final emails generation.")
            else:
                print("\nFailed to generate master email draft.")
        else:
            print("\nFailed to validate contacts.")
    else:
        print("\nFailed to execute OSINT enrichment.")
