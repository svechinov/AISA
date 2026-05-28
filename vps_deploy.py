import paramiko
import os
import sys

HOST = "95.163.223.186"
USER = "root"
PASS = "sWJev7IFn6Jm2zg1"
LOCAL_DIR = r"C:\Users\user\AI-Biz-OS"
REMOTE_DIR = "/var/www/AI-Biz-OS"

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

def upload_dir(sftp, local_dir, remote_dir):
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass
    
    for item in os.listdir(local_dir):
        # Skip git, node_modules, and dist to save time/space
        if item in ['.git', 'node_modules', '__pycache__', 'dist']:
            continue
            
        local_path = os.path.join(local_dir, item)
        remote_path = remote_dir + '/' + item
        
        if os.path.isfile(local_path):
            print(f"Uploading {local_path} to {remote_path}")
            sftp.put(local_path, remote_path)
        elif os.path.isdir(local_path):
            upload_dir(sftp, local_path, remote_path)

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    print(f"Connecting to {HOST}...")
    try:
        ssh.connect(HOST, username=USER, password=PASS, timeout=10)
        print("Connected successfully!")
        
        # 1. Fix DB Permission Command
        setup_db_script = """
sudo -u postgres psql -c "GRANT ALL ON SCHEMA public TO aibizos;" aibizos_db
"""
        execute_command(ssh, setup_db_script)
        
        # 2. Upload Code (since git clone failed)
        execute_command(ssh, f"mkdir -p {REMOTE_DIR}")
        sftp = ssh.open_sftp()
        print("Starting code upload...")
        upload_dir(sftp, LOCAL_DIR, REMOTE_DIR)
        sftp.close()
        print("Code upload completed.")
        
        # 3. Setup Python Virtual Environment and Install Backend requirements
        setup_backend_script = """
cd /var/www/AI-Biz-OS/backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
"""
        execute_command(ssh, setup_backend_script)
        
        # 4. Create .env file for Backend
        env_content = """
DATABASE_URL=postgresql://aibizos:aibizospassword@localhost:5432/aibizos_db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=supersecretkey_change_me_later
DEBUG=True
"""
        execute_command(ssh, f"cat << 'EOF' > /var/www/AI-Biz-OS/backend/.env\n{env_content}\nEOF")
        
        # 5. Run Migrations
        execute_command(ssh, "cd /var/www/AI-Biz-OS/backend && ./venv/bin/alembic upgrade head")
        
        # 6. Setup systemd service for backend
        service_content = """[Unit]
Description=AI-Biz-OS FastAPI Backend
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/var/www/AI-Biz-OS/backend
Environment="PATH=/var/www/AI-Biz-OS/backend/venv/bin"
ExecStart=/var/www/AI-Biz-OS/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

[Install]
WantedBy=multi-user.target
"""
        execute_command(ssh, f"cat << 'EOF' > /etc/systemd/system/aibizos.service\n{service_content}\nEOF")
        execute_command(ssh, "systemctl daemon-reload && systemctl enable aibizos && systemctl start aibizos")
        
        print("\nBackend setup completed!")
        
    except Exception as e:
        print(f"Connection or execution failed: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
