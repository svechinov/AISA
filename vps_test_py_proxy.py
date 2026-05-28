import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.163.223.186', username='root', password='sWJev7IFn6Jm2zg1')

test_py = '''
import httpx
import os
import sys

# Try manually
proxy = "http://gaGN4f:0og1Gt@91.233.54.62:8000"
print(f"Testing with proxy: {proxy}")

try:
    with httpx.Client(proxy=proxy, timeout=10) as client:
        r = client.get("https://api.openai.com/v1/chat/completions")
        print(f"Status: {r.status_code}")
        print(f"Body: {r.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
'''

sftp = ssh.open_sftp()
with sftp.file('/var/www/AI-Biz-OS/backend/test_proxy_direct.py', 'w') as f:
    f.write(test_py)
sftp.close()

stdin, stdout, stderr = ssh.exec_command('cd /var/www/AI-Biz-OS/backend && ./venv/bin/python test_proxy_direct.py')
print(stdout.read().decode())
print(stderr.read().decode())

ssh.close()
