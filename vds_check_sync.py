import paramiko
import os
import sys

HOST = "95.163.223.186"
USER = "root"
PASS = "sWJev7IFn6Jm2zg1"
REMOTE_DIR = "/var/www/AI-Biz-OS"

def execute_command(ssh, command):
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace').strip()
    return out

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(HOST, username=USER, password=PASS, timeout=10)
        
        # Check git status on the VPS
        print("Checking Git status on VDS...")
        out = execute_command(ssh, f"cd {REMOTE_DIR} && git status")
        print("--- VDS GIT STATUS ---")
        print(out)
        print("----------------------")
        
        # Check if there are any modified python files
        out = execute_command(ssh, f"cd {REMOTE_DIR} && find . -name '*.py' -type f -mtime -2")
        print("\nRecently modified Python files on VDS (last 2 days):")
        print(out)
        
    except Exception as e:
        print(f"Failed: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
