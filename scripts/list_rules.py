import os
import paramiko

def list_rules():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('95.163.223.186', username='root', password=os.environ.get("VDS_PASS", ""))
    
    cmd = "SELECT id, scope, step_name, left(content, 100) FROM rules WHERE active = true;"
    full_cmd = f'sudo -u postgres psql -d aibizos_db -c "{cmd}"'
    print(f"Executing: {cmd}")
    stdin, stdout, stderr = ssh.exec_command(full_cmd)
    print(stdout.read().decode())
    
    ssh.close()

if __name__ == "__main__":
    list_rules()
