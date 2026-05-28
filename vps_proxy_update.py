import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.163.223.186', username='root', password='sWJev7IFn6Jm2zg1')

# Format: http://user:pass@ip:port
proxy_str = 'http://gaGN4f:0og1Gt@91.233.54.62:8000'
ssh.exec_command(f'echo "HTTP_PROXY={proxy_str}" >> /var/www/AI-Biz-OS/backend/.env')

sftp = ssh.open_sftp()
sftp.put(r'C:\Users\user\AI-Biz-OS\backend\app\config.py', '/var/www/AI-Biz-OS/backend/app/config.py')
sftp.put(r'C:\Users\user\AI-Biz-OS\backend\app\services\llm_gateway.py', '/var/www/AI-Biz-OS/backend/app/services/llm_gateway.py')
sftp.close()

ssh.exec_command('systemctl restart aibizos')
print('Backend updated with proxy support')
ssh.close()
