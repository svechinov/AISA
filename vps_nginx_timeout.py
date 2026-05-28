import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.163.223.186', username='root', password='sWJev7IFn6Jm2zg1')

nginx_config = '''
server {
    listen 80 default_server;
    server_name _;

    root /var/www/AI-Biz-OS/frontend/dist;
    index index.html;

    # Increase body size for uploads
    client_max_body_size 100M;

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

        # INCREASED TIMEOUTS FOR AI OPERATIONS
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
    }
}
'''

sftp = ssh.open_sftp()
with sftp.file('/etc/nginx/sites-available/aibizos', 'w') as f:
    f.write(nginx_config)
sftp.close()

ssh.exec_command('systemctl restart nginx')
print('Nginx restarted with higher timeouts')
ssh.close()
