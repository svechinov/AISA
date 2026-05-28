import paramiko
import time
import sys

HOST = "95.163.223.186"
USER = "root"
PASS = "sWJev7IFn6Jm2zg1"

def execute_command(ssh, command, hide_output=False):
    if not hide_output:
        print(f"\n[VPS] Executing: {command}")
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    
    if not hide_output:
        if out:
            print(out)
        if err:
            print(f"Error output:\n{err}")
    
    return exit_status, out, err

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    print(f"Connecting to {HOST}...")
    try:
        ssh.connect(HOST, username=USER, password=PASS, timeout=10)
        print("Connected successfully!")
        
        # 1. Update system and install requirements
        execute_command(ssh, "apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y")
        execute_command(ssh, "DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-contrib redis-server python3-pip python3-venv git nginx curl")
        
        # 2. Setup PostgreSQL
        # Create database and user (if not exists)
        setup_db_script = """
sudo -u postgres psql -c "CREATE USER aibizos WITH PASSWORD 'aibizospassword';"
sudo -u postgres psql -c "CREATE DATABASE aibizos_db OWNER aibizos;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE aibizos_db TO aibizos;"
sudo -u postgres psql -c "\\c aibizos_db; GRANT ALL ON SCHEMA public TO aibizos;"
"""
        execute_command(ssh, setup_db_script)
        
        # 3. Setup Project Directory
        execute_command(ssh, "mkdir -p /var/www && cd /var/www && if [ ! -d 'AI-Biz-OS' ]; then git clone https://github.com/PavelMuntyan/AI-Biz-OS.git; else cd AI-Biz-OS && git pull; fi")
        
        # 4. Setup Python Virtual Environment and Install Backend requirements
        setup_backend_script = """
cd /var/www/AI-Biz-OS/backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
"""
        execute_command(ssh, setup_backend_script)
        
        # 5. Create .env file for Backend
        env_content = """
DATABASE_URL=postgresql://aibizos:aibizospassword@localhost:5432/aibizos_db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=supersecretkey_change_me_later
DEBUG=True
"""
        execute_command(ssh, f"cat << 'EOF' > /var/www/AI-Biz-OS/backend/.env\n{env_content}\nEOF")
        
        # 6. Run Migrations
        execute_command(ssh, "cd /var/www/AI-Biz-OS/backend && ./venv/bin/alembic upgrade head")
        
        print("\nInitial VPS setup completed!")
        
    except Exception as e:
        print(f"Connection or execution failed: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
