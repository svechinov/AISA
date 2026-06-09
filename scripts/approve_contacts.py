import os
import paramiko

def approve_all_contacts(run_id):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('95.163.223.186', username='root', password=os.environ.get("VDS_PASS", ""))
    
    cmd = f"UPDATE contacts SET review_status = 'approved' WHERE run_id = {run_id};"
    full_cmd = f'sudo -u postgres psql -d aibizos_db -c "{cmd}"'
    print(f"Executing: {cmd}")
    stdin, stdout, stderr = ssh.exec_command(full_cmd)
    print(stdout.read().decode())
    
    ssh.close()

if __name__ == "__main__":
    approve_all_contacts(11)
