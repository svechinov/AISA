import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.163.223.186', username='root', password='sWJev7IFn6Jm2zg1')

# Test direct curl with proxy
print("--- Testing Proxy with CURL ---")
test_cmd = 'curl -I -x http://gaGN4f:0og1Gt@91.233.54.62:8000 https://api.openai.com/v1/chat/completions'
stdin, stdout, stderr = ssh.exec_command(test_cmd)
print(stdout.read().decode())
print(stderr.read().decode())

# Check .env
print("--- Checking .env Content ---")
stdin, stdout, stderr = ssh.exec_command('cat /var/www/AI-Biz-OS/backend/.env')
print(stdout.read().decode())

ssh.close()
