import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

OWNER = "davi-souza-vmg"
REPO = "Phytons"
API_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
APP_ASSET = "RenomeadorApp.exe"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RenomeadorDP"
VERSIONS_DIR = APP_DIR / "versions"
TIMEOUT = 12


def request_json(url):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "RenomeadorDP-Updater"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def notify(title, message, kind="info"):
    root = tk.Tk()
    root.withdraw()
    try:
        if kind == "error":
            messagebox.showerror(title, message, parent=root)
        elif kind == "warning":
            messagebox.showwarning(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
    finally:
        root.destroy()


def download_to(url, destination):
    req = urllib.request.Request(url, headers={"User-Agent": "RenomeadorDP-Updater"})
    with urllib.request.urlopen(req, timeout=60) as response, open(destination, "wb") as out:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_app(app_path, version):
    env = os.environ.copy()
    env["RENOMEADOR_VERSION"] = f"{version} • Atualizador GitHub"
    env["RENOMEADOR_PASTA_ENTRADA"] = str(Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent)
    subprocess.Popen([str(app_path)], cwd=env["RENOMEADOR_PASTA_ENTRADA"], env=env)


def main():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    local_version_file = APP_DIR / "versao_instalada.txt"
    local_version = local_version_file.read_text(encoding="utf-8").strip() if local_version_file.exists() else ""

    try:
        release = request_json(API_URL)
        version = release.get("tag_name", "").strip()
        if not version or release.get("draft") or release.get("prerelease"):
            raise ValueError("O GitHub não retornou uma versão estável publicada.")
        assets = {asset.get("name"): asset for asset in release.get("assets", [])}
        asset = assets.get(APP_ASSET)
        if not asset or not asset.get("browser_download_url"):
            raise ValueError(f"A versão {version} não contém o arquivo {APP_ASSET}.")

        app_path = VERSIONS_DIR / version / APP_ASSET
        if local_version != version or not app_path.is_file():
            root = tk.Tk()
            root.title("Renomeador de Documentos")
            root.geometry("430x150")
            root.resizable(False, False)
            root.configure(bg="#f5f7fb")
            tk.Label(root, text="Verificando atualizações", bg="#f5f7fb", fg="#172033", font=("Segoe UI", 14, "bold")).pack(pady=(22, 6))
            status = tk.Label(root, text=f"Preparando a versão {version}…", bg="#f5f7fb", fg="#6b7280", font=("Segoe UI", 10))
            status.pack(pady=3)
            bar = ttk.Progressbar(root, mode="indeterminate", length=330)
            bar.pack(pady=12)
            bar.start(10)
            root.update()
            temp_dir = VERSIONS_DIR / f".download_{version}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = temp_dir / APP_ASSET
            try:
                status.configure(text=f"Baixando {version} do GitHub…")
                root.update()
                download_to(asset["browser_download_url"], temp_file)
                expected_digest = asset.get("digest", "")
                if expected_digest.startswith("sha256:"):
                    actual = sha256_file(temp_file)
                    if actual.lower() != expected_digest.split(":", 1)[1].lower():
                        raise ValueError("A verificação de integridade do download falhou. O arquivo não foi instalado.")
                elif temp_file.stat().st_size < 1_000_000:
                    raise ValueError("O executável baixado parece incompleto; a atualização foi cancelada.")
                version_dir = VERSIONS_DIR / version
                version_dir.mkdir(parents=True, exist_ok=True)
                os.replace(temp_file, version_dir / APP_ASSET)
                local_version_file.write_text(version, encoding="utf-8")
                app_path = version_dir / APP_ASSET
            finally:
                bar.stop()
                root.destroy()
                try:
                    if temp_dir.exists():
                        for child in temp_dir.iterdir():
                            child.unlink(missing_ok=True)
                        temp_dir.rmdir()
                except OSError:
                    pass
        run_app(app_path, version)
    except Exception as exc:
        # If GitHub is unavailable, run the last cached valid executable if present.
        cached = sorted(
            (p for p in VERSIONS_DIR.glob("*/" + APP_ASSET) if p.is_file()),
            key=lambda p: p.parent.name,
            reverse=True,
        )
        if cached:
            notify("Atualização indisponível", f"Não foi possível verificar/baixar a atualização.\n\nDetalhe: {exc}\n\nO Renomeador será aberto com a última versão local disponível.", "warning")
            run_app(cached[0], cached[0].parent.name)
        else:
            notify(
                "Não foi possível iniciar o Renomeador",
                "O programa ainda não tem uma versão instalada e não foi possível baixar uma do GitHub.\n\n"
                f"Detalhe: {exc}\n\nVerifique a conexão com a internet e se existe uma Release publicada no repositório.",
                "error",
            )


if __name__ == "__main__":
    main()
