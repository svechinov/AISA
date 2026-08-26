import os
import paramiko

VDS_HOST = os.environ.get("VDS_HOST", "<your-server-ip>")

def check_db_counts():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VDS_HOST, username='root', password=os.environ.get("VDS_PASS", ""))
    
    commands = [
        'SELECT count(*) FROM run_companies WHERE run_id = 11;',
        'SELECT count(*) FROM contacts WHERE run_id = 11;',
        'SELECT count(*) FROM entity_json_kv WHERE scope = \'run_company_extra\' AND entity_id IN (SELECT id FROM run_companies WHERE run_id = 11);'
    ]
    
    for cmd in commands:
        full_cmd = f'sudo -u postgres psql -d aibizos_db -c "{cmd}"'
        print(f"\nExecuting: {cmd}")
        stdin, stdout, stderr = ssh.exec_command(full_cmd)
        print(stdout.read().decode())
        
    ssh.close()

if __name__ == "__main__":
    check_db_counts()
