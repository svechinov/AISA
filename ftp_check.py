import ftplib
import os
import sys

FTP_HOST = "fgsales.ru"
FTP_USER = "u3519625_asvechinov"
FTP_PASS = "aB9rW7nK5ggT0wZ2"

def upload_dir(ftp, local_dir, remote_dir):
    try:
        ftp.mkd(remote_dir)
    except ftplib.error_perm:
        pass
    
    ftp.cwd(remote_dir)
    
    for item in os.listdir(local_dir):
        local_path = os.path.join(local_dir, item)
        if os.path.isfile(local_path):
            print(f"Uploading {item} to {remote_dir}...")
            with open(local_path, 'rb') as f:
                ftp.storbinary(f"STOR {item}", f)
        elif os.path.isdir(local_path):
            upload_dir(ftp, local_path, item)
            ftp.cwd("..")

def main():
    local_dist = r"C:\Users\user\AI-Biz-OS\frontend\dist"
    
    if not os.path.exists(local_dist):
        print(f"Error: {local_dist} does not exist.")
        sys.exit(1)
        
    print(f"Connecting to {FTP_HOST}...")
    try:
        with ftplib.FTP(FTP_HOST, FTP_USER, FTP_PASS) as ftp:
            print("Connected. Logging in...")
            print("Current directory:", ftp.pwd())
            print("Root directory listing:")
            ftp.dir()
            
            # Let's upload to root for now, or public_html if it exists.
            # We'll just upload the contents of dist to the current directory.
            # But wait, we should upload contents of dist, not dist itself, to the web root.
            # Let's just list the directory first so we know where to upload in the next step.
            
    except Exception as e:
        print(f"FTP error: {e}")

if __name__ == "__main__":
    main()
