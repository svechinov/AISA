import paramiko

def run_migration():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('95.163.223.186', username='root', password='sWJev7IFn6Jm2zg1')
    
    sql = """
    ALTER TABLE run_setups ADD COLUMN IF NOT EXISTS osint_prompt TEXT;
    ALTER TABLE run_setups ADD COLUMN IF NOT EXISTS reasoning_prompt TEXT;
    ALTER TABLE run_setups ADD COLUMN IF NOT EXISTS draft_prompt TEXT;
    ALTER TABLE run_setups ADD COLUMN IF NOT EXISTS language VARCHAR(50) DEFAULT 'Russian';
    """
    
    full_cmd = f'sudo -u postgres psql -d aibizos_db -c "{sql}"'
    print(f"Executing migration...")
    stdin, stdout, stderr = ssh.exec_command(full_cmd)
    print(stdout.read().decode())
    print(stderr.read().decode())
    
    ssh.close()

if __name__ == "__main__":
    run_migration()
