import paramiko
import os
import sys

# Deploy target & all secrets come from environment — never hardcode them in this file
# (hardcoded keys here were leaked on push and auto-revoked by the provider). Set before running,
# e.g. via a gitignored .env.deploy loaded with python-dotenv, or plain env vars.
HOST = os.environ.get("VDS_HOST", "")
USER = os.environ.get("VDS_USER", "root")
PASS = os.environ.get("VDS_PASS", "")
LOCAL_DIR = os.environ.get("VDS_LOCAL_DIR", r"C:\Users\user\AI-Biz-OS")
REMOTE_DIR = os.environ.get("VDS_REMOTE_DIR", "/var/www/AI-Biz-OS")

if not HOST or not PASS:
    sys.exit("Set VDS_HOST and VDS_PASS env vars (deploy secrets are not stored in this file).")

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
        # All secret values are read from the deployer's environment — none are stored in this file.
        env_content = f"""
DATABASE_URL={os.environ.get("DEPLOY_DATABASE_URL", "sqlite:///./ai_biz_os.db")}
REDIS_URL=redis://localhost:6379/0
SECRET_KEY={os.environ.get("SECRET_KEY", "")}
DEBUG=True

# LLM Config
LLM_PROVIDER_PRIORITY=openai
OPENAI_API_KEY={os.environ.get("OPENAI_API_KEY", "")}
TAVILY_API_KEY={os.environ.get("TAVILY_API_KEY", "")}

# CDN Config (Cloudflare R2)
CDN_PROVIDER=cloudflare
CDN_ACCOUNT_ID={os.environ.get("CDN_ACCOUNT_ID", "")}
CDN_API_KEY={os.environ.get("CDN_API_KEY", "")}
CDN_R2_BUCKET={os.environ.get("CDN_R2_BUCKET", "fgc")}
CDN_R2_ACCESS_KEY_ID={os.environ.get("CDN_R2_ACCESS_KEY_ID", "")}
CDN_R2_SECRET_ACCESS_KEY={os.environ.get("CDN_R2_SECRET_ACCESS_KEY", "")}
CDN_R2_PUBLIC_BASE_URL={os.environ.get("CDN_R2_PUBLIC_BASE_URL", "")}
GLOBAL_PASSWORD={os.environ.get("GLOBAL_PASSWORD", "")}
HTTP_PROXY={os.environ.get("HTTP_PROXY", "")}
"""
        execute_command(ssh, f"cat << 'EOF' > /var/www/AI-Biz-OS/backend/.env\n{env_content}\nEOF")
        
        # 5. Run Migrations (Manual Column Additions for GSD 2.1)
        migration_sql = """
        ALTER TABLE run_setups ADD COLUMN IF NOT EXISTS osint_prompt TEXT;
        ALTER TABLE run_setups ADD COLUMN IF NOT EXISTS reasoning_prompt TEXT;
        ALTER TABLE run_setups ADD COLUMN IF NOT EXISTS draft_prompt TEXT;
        ALTER TABLE run_setups ADD COLUMN IF NOT EXISTS language VARCHAR(50) DEFAULT 'Russian';
        """
        execute_command(ssh, f'sudo -u postgres psql -d aibizos_db -c "{migration_sql}"')
        
        # 6. Setup systemd service for backend
        service_content = """[Unit]
Description=AI-Biz-OS FastAPI Backend
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/var/www/AI-Biz-OS/backend
Environment="PATH=/var/www/AI-Biz-OS/backend/venv/bin"
Environment="PYTHONPATH=/var/www/AI-Biz-OS/backend"
ExecStart=/var/www/AI-Biz-OS/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

[Install]
WantedBy=multi-user.target
"""
        execute_command(ssh, f"cat << 'EOF' > /etc/systemd/system/aibizos.service\n{service_content}\nEOF")
        execute_command(ssh, "systemctl daemon-reload && systemctl enable aibizos && systemctl restart aibizos")
        
        print("\nBackend setup completed!")
        
    except Exception as e:
        print(f"Connection or execution failed: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
