import os
import subprocess

REPO_URL = "https://github.com/ekinciimuhammed/appremovermac.git"

def run(cmd):
    print(f"[RUN] {cmd}")
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if result.stdout:
        print("[OUT]\n", result.stdout)
    if result.stderr:
        print("[ERR]\n", result.stderr)
    return result.returncode  # hiçbir şeyi durdurma, sadece sonucu dön

def ensure_git_repo():
    if not os.path.exists(".git"):
        print("[INFO] .git bulunamadı, git init yapılıyor...")
        run("git init")
    else:
        print("[INFO] Git repo zaten var.")

def ensure_remote():
    print("[INFO] Remote origin kontrol ediliyor...")
    code = run("git remote get-url origin")
    if code != 0:
        print("[INFO] Remote origin ekleniyor...")
        run(f"git remote add origin {REPO_URL}")
    else:
        print("[INFO] Remote origin zaten var.")

def delete_local_branch(branch):
    print(f"[INFO] Local branch '{branch}' silinmeye çalışılıyor...")
    run(f"git branch -D {branch}")

def delete_remote_branch(branch):
    print(f"[INFO] Remote branch '{branch}' silinmeye çalışılıyor (--force overwrite için)...")
    run(f"git push origin --delete {branch}")

def main():
    ensure_git_repo()
    ensure_remote()

    branch = input("Yeni branch adı: ").strip()
    if not branch:
        print("[ERROR] Branch adı boş olamaz.")
        return

    print(f"\n=== BRANCH OVERWRITE MODU AKTİF: {branch} ===")

    # 1) LOCAL BRANCH SİL
    delete_local_branch(branch)

    # 2) REMOTE BRANCH SİL
    delete_remote_branch(branch)

    # 3) YENİDEN OLUŞTUR
    print(f"[INFO] Yeni branch oluşturuluyor: {branch}")
    run(f"git checkout -b {branch}")

    # 4) ADD ALL
    print("[INFO] Tüm dosyalar ekleniyor (git add .)...")
    run("git add .")

    # 5) COMMIT
    commit_msg = f"Versiyon15 -daha stabil {branch}"
    print(f"[INFO] Commit: '{commit_msg}'")
    run(f'git commit -m "{commit_msg}"')

    # 6) FORCE PUSH
    print(f"[INFO] Branch remote'a FORCE olarak gönderiliyor...")
    run(f"git push -u origin {branch} --force")

    print("\n[SUCCESS] Branch force overwrite ile başarıyla gönderildi.")

if __name__ == "__main__":
    main()