import paramiko
import os

HOST = "95.163.223.186"
USER = "root"
PASS = "sWJev7IFn6Jm2zg1"
LOCAL_DIST = r"C:\Users\user\AI-Biz-OS\frontend\dist"
REMOTE_DIST = "/var/www/AI-Biz-OS/frontend/dist"

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
        
        # 1. Initialize Database
        execute_command(ssh, "cd /var/www/AI-Biz-OS/backend && ./venv/bin/python app/init_db.py")
        
        # 2. Upload Frontend Dist
        execute_command(ssh, f"mkdir -p {REMOTE_DIST}")
        sftp = ssh.open_sftp()
        print("Starting frontend upload...")
        upload_dir(sftp, LOCAL_DIST, REMOTE_DIST)
        sftp.close()
        print("Frontend upload completed.")
        
        # 3. Configure Nginx
        nginx_config = """
server {
    listen 80 default_server;
    server_name _;

    root /var/www/AI-Biz-OS/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
"""
        execute_command(ssh, f"cat << 'EOF' > /etc/nginx/sites-available/aibizos\n{nginx_config}\nEOF")
        execute_command(ssh, "rm -f /etc/nginx/sites-enabled/default")
        execute_command(ssh, "ln -sf /etc/nginx/sites-available/aibizos /etc/nginx/sites-enabled/")
        execute_command(ssh, "systemctl restart nginx")
        
        print("\nNginx and Database setup completed! Check http://95.163.223.186")
        
    except Exception as e:
        print(f"Connection or execution failed: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
