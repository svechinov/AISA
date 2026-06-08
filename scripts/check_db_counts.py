import paramiko

def check_db_counts():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('95.163.223.186', username='root', password='sWJev7IFn6Jm2zg1')
    
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
