import os
import re
import time
import shutil
import subprocess
import sys
import logging
import json
import hashlib
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from pypdf import PdfReader, PdfWriter

logging.getLogger("pypdf").setLevel(logging.ERROR)


class ProcessingError(RuntimeError):
    """Erro operacional que deve interromper o processamento e aparecer na interface."""


TIPOS = {
    "1": "relatório de ponto",
    "2": "contracheque",
    "3": "espelho de ponto",
}

TIPOS_PONTO = {
    "1": "relatório de ponto",
    "2": "ficha de ponto",
    "3": "cartao de ponto",
}

MESES = {
    1: "01-JANEIRO",
    2: "02-FEVEREIRO",
    3: "03-MARÇO",
    4: "04-ABRIL",
    5: "05-MAIO",
    6: "06-JUNHO",
    7: "07-JULHO",
    8: "08-AGOSTO",
    9: "09-SETEMBRO",
    10: "10-OUTUBRO",
    11: "11-NOVEMBRO",
    12: "12-DEZEMBRO",
}

ORDEM_PDF_AGRUPADO = [
    "espelho de ponto",
    "ponto",
    "contracheque",
]

def limpar_nome(nome):
    return re.sub(r'[<>:"/\\|?*]', '', nome).strip()


def nome_funcionario_sem_codigo(nome):
    """Remove o código final do nome, por exemplo: 'Davi Souza Ribeiro - 50'."""
    return re.sub(r"\s*-\s*\d+\s*$", "", nome).strip()


def listar_anos(pasta_funcionario):
    """Lista as pastas de ano existentes dentro da pasta do funcionário."""
    try:
        anos = [
            item.name
            for item in Path(pasta_funcionario).iterdir()
            if item.is_dir() and re.fullmatch(r"\d{4}", item.name)
        ]
        return sorted(anos, reverse=True)
    except (FileNotFoundError, PermissionError):
        return []


def listar_meses_existentes(pasta_ano):
    """Lista os meses já existentes dentro de uma pasta de ano."""
    try:
        pasta_ano = Path(pasta_ano)
        if not pasta_ano.is_dir():
            return []

        encontrados = []
        for item in pasta_ano.iterdir():
            if not item.is_dir():
                continue

            match = re.match(r"^\s*(\d{1,2})\s*[-—]\s*(.+?)\s*$", item.name)
            if not match:
                continue

            numero = int(match.group(1))
            if 1 <= numero <= 12:
                encontrados.append((numero, item.name))

        return sorted(encontrados, key=lambda x: x[0])
    except (FileNotFoundError, PermissionError):
        return []


def preparar_pasta_ano_mes(pasta_funcionario, ano, numero_mes):
    pasta_ano = pasta_funcionario / ano
    pasta_ano.mkdir(parents=True, exist_ok=True)

    pasta_mes = pasta_ano / MESES[numero_mes]
    pasta_mes.mkdir(parents=True, exist_ok=True)
    return pasta_mes



def arquivos_pdf(pasta):
    try:
        if not pasta.is_dir():
            raise ProcessingError(f"A pasta de entrada não existe ou não está acessível:\n{pasta}")
        return {
            arquivo.resolve()
            for arquivo in pasta.iterdir()
            if arquivo.is_file()
            and arquivo.suffix.lower() == ".pdf"
            and not arquivo.name.startswith("~$")
        }
    except ProcessingError:
        raise
    except OSError as erro:
        raise ProcessingError(f"Não foi possível verificar a pasta de entrada:\n{pasta}\n\nDetalhes: {erro}") from erro


def arquivo_estavel(arquivo, segundos=1):
    try:
        tamanho1 = arquivo.stat().st_size
        time.sleep(segundos)
        tamanho2 = arquivo.stat().st_size
        return tamanho1 == tamanho2 and tamanho2 > 0
    except FileNotFoundError:
        # O scanner pode ainda estar terminando ou removendo o arquivo.
        return False
    except PermissionError as erro:
        raise ProcessingError(
            f"Sem permissão para acessar o PDF:\n{arquivo.name}\n\nDetalhes: {erro}"
        ) from erro
    except OSError as erro:
        raise ProcessingError(
            f"Não foi possível verificar se o PDF terminou de ser gravado:\n{arquivo.name}\n\nDetalhes: {erro}"
        ) from erro


def obter_numero_paginas(arquivo):
    try:
        leitor = PdfReader(str(arquivo))
        return len(leitor.pages)
    except Exception as erro:
        raise ProcessingError(
            f"Não foi possível ler o PDF:\n{arquivo.name}\n\n"
            f"Verifique se o arquivo não está corrompido ou protegido.\n\nDetalhes: {erro}"
        ) from erro


def criar_pdf_de_paginas(leitor, inicio, fim, destino):
    escritor = PdfWriter()
    for numero_pagina in range(inicio, fim):
        escritor.add_page(leitor.pages[numero_pagina])

    with destino.open("wb") as arquivo_saida:
        escritor.write(arquivo_saida)



def processar_pdf_agrupado(
    arquivo,
    pasta_destino,
    nome_funcionario,
    ano,
    numero_mes,
    configuracao,
    notificar=None,
):
    def avisar(tipo, detalhe=None):
        if notificar:
            notificar(tipo, detalhe)

    avisar("scan", "PDF detectado. Preparando a separação…")
    numero_paginas = obter_numero_paginas(arquivo)

    esperado = configuracao["total_paginas"]

    if numero_paginas != esperado:
        raise ProcessingError(
            "A quantidade de páginas do PDF não confere.\n\n"
            f"Arquivo recebido: {arquivo.name}\n"
            f"Páginas recebidas: {numero_paginas}\n"
            f"Páginas esperadas: {esperado}\n\n"
            "O PDF original foi mantido. Confira a ordem do escaneamento e a configuração."
        )

    leitor = PdfReader(str(arquivo))

    blocos = [
        ("espelho de ponto", 0, configuracao["paginas_espelho"]),
        (
            configuracao["tipo_ponto"],
            configuracao["paginas_espelho"],
            configuracao["paginas_ponto"],
        ),
        (
            "contracheque",
            configuracao["paginas_espelho"] + configuracao["paginas_ponto"],
            configuracao["paginas_contracheque"],
        ),
    ]

    temporarios = []
    destinos = []

    try:
        total_blocos = len(blocos)
        for indice_bloco, (tipo, inicio, quantidade) in enumerate(blocos, start=1):
            avisar("progress", (indice_bloco - 1, total_blocos, f"Separando {tipo}…"))
            destino_final = pasta_destino / (
                f"{nome_funcionario} - {tipo} {numero_mes:02d} {ano}.pdf"
            )

            if destino_final.exists():
                raise ProcessingError(
                    f"Já existe um arquivo com este nome na pasta de destino:\n"
                    f"{destino_final.name}\n\n"
                    "Nenhum arquivo existente foi sobrescrito. O PDF original foi mantido."
                )

            temp = pasta_destino / (
                f".tmp_{arquivo.stem}_{tipo.replace(' ', '_')}.pdf"
            )

            if temp.exists():
                temp.unlink()

            escritor = PdfWriter()
            for pagina in range(inicio, inicio + quantidade):
                escritor.add_page(leitor.pages[pagina])
                avisar("page", (pagina + 1, numero_paginas, f"Lendo página {pagina + 1} de {numero_paginas}"))

            with temp.open("wb") as arquivo_saida:
                escritor.write(arquivo_saida)

            temporarios.append(temp)
            destinos.append(destino_final)

        for temp, destino in zip(temporarios, destinos):
            shutil.move(str(temp), str(destino))
            avisar("progress", (len(destinos), len(destinos), f"Documento salvo: {destino.name}"))

        arquivo.unlink()

        print("\n╔══════════════════════════════════════════╗")
        print("║       PDF SEPARADO COM SUCESSO!         ║")
        print("╚══════════════════════════════════════════╝")
        print("\nOs documentos foram organizados assim:")
        for destino in destinos:
            print(f"✓ {destino.name}")

        avisar("separated", str(pasta_destino))
        return True

    except Exception as erro:
        for temp in temporarios:
            try:
                if temp.exists():
                    temp.unlink()
            except OSError:
                pass
        if isinstance(erro, ProcessingError):
            raise
        raise ProcessingError(
            f"Não foi possível separar o PDF {arquivo.name}.\n\n"
            f"O arquivo original foi mantido sempre que possível.\n\nDetalhes: {erro}"
        ) from erro


def assinatura_arquivo(arquivo):
    """Identifica uma versão específica do arquivo para evitar mensagens repetidas."""
    try:
        stat = arquivo.stat()
        return (str(arquivo.resolve()), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


def processar_pdfs(
    pasta_origem,
    pasta_destino,
    nome_funcionario,
    ano,
    numero_mes,
    configuracao=None,
    notificar=None,
):
    def avisar(tipo, detalhe=None):
        if notificar:
            notificar(tipo, detalhe)

    if configuracao is None:
        raise ProcessingError("A configuração dos documentos não foi definida.")

    pasta_origem = Path(pasta_origem)
    pasta_destino = Path(pasta_destino)
    if not pasta_destino.is_dir():
        raise ProcessingError(f"A pasta de destino não existe ou não está acessível:\n{pasta_destino}")

    while True:
        arquivo = obter_proximo_pdf(pasta_origem)
        avisar("scan", f"PDF detectado: {arquivo.name}. Iniciando a leitura…")
        numero_paginas = obter_numero_paginas(arquivo)
        esperado = configuracao["total_paginas"]

        if numero_paginas != esperado:
            raise ProcessingError(
                "A quantidade de páginas do PDF não confere.\n\n"
                f"Arquivo recebido: {arquivo.name}\n"
                f"Páginas recebidas: {numero_paginas}\n"
                f"Páginas esperadas: {esperado}\n\n"
                "O PDF original foi mantido. Corrija o escaneamento ou a configuração e tente novamente."
            )

        processar_pdf_agrupado(
            arquivo,
            pasta_destino,
            nome_funcionario,
            ano,
            numero_mes,
            configuracao,
            notificar=avisar,
        )
        return


def obter_proximo_pdf(pasta_origem, assinatura_ignorada=None):
    """Encontra o próximo PDF disponível na pasta de entrada."""
    while True:
        atuais = arquivos_pdf(pasta_origem)

        if atuais:
            # Sempre haverá apenas um PDF por vez.
            # Se houver mais de um por acidente, pega o mais antigo.
            candidatos = [
                arquivo
                for arquivo in atuais
                if assinatura_arquivo(arquivo) != assinatura_ignorada
            ]

            if candidatos:
                try:
                    candidato = min(candidatos, key=lambda arquivo: arquivo.stat().st_mtime)
                except OSError as erro:
                    raise ProcessingError(f"Não foi possível acessar um PDF na pasta de entrada.\n\nDetalhes: {erro}") from erro

                if arquivo_estavel(candidato):
                    return candidato

        time.sleep(0.5)





import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# ============================================================
# INTERFACE GRÁFICA — RENOMEADOR DE DOCUMENTOS DP
# ============================================================

APP_TITLE = "Renomeador de Documentos — DP"
APP_VERSION = "v17.0.0"

BG = "#f5f7fb"
CARD = "#ffffff"
TEXT = "#172033"
MUTED = "#6b7280"
PRIMARY = "#2563eb"
PRIMARY_DARK = "#1d4ed8"
SUCCESS = "#16a34a"
WARNING = "#d97706"
BORDER = "#e5e7eb"

MESES_UI = {
    1: "01 — Janeiro", 2: "02 — Fevereiro", 3: "03 — Março",
    4: "04 — Abril", 5: "05 — Maio", 6: "06 — Junho",
    7: "07 — Julho", 8: "08 — Agosto", 9: "09 — Setembro",
    10: "10 — Outubro", 11: "11 — Novembro", 12: "12 — Dezembro",
}

TIPOS_PONTO_UI = {
    "Relatório de ponto": "relatório de ponto",
    "Ficha de ponto": "ficha de ponto",
    "Cartão de ponto": "cartao de ponto",
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("980x720")
        self.minsize(860, 640)
        self.configure(bg=BG)

        self.pasta_funcionario = None
        self.ano = None
        self.numero_mes = None
        self.pasta_destino = None
        self.configuracao = None
        self.worker = None
        self.running = False
        self.events = queue.Queue()
        self.scan_canvas = None
        self.scan_animation_id = None
        self.scan_phase = 0
        self.scan_active = False

        self.var_pasta = tk.StringVar(value="Nenhuma pasta selecionada")
        self.var_funcionario = tk.StringVar(value="—")
        self.var_ano = tk.StringVar()
        self.var_mes = tk.StringVar()
        self.var_tipo_ponto = tk.StringVar(value="Relatório de ponto")
        self.var_espelho = tk.StringVar(value="1")
        self.var_ponto = tk.StringVar(value="1")
        self.var_contracheque = tk.StringVar(value="1")
        self.var_status = tk.StringVar(value="Pronto para começar")
        self.var_step = tk.IntVar(value=1)

        self._style()
        self._build()
        self.after(100, self._poll_events)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", font=("Segoe UI", 10))
        style.configure("TCombobox", padding=9, fieldbackground="white")
        style.configure("TEntry", padding=9)
        style.configure(
            "Primary.TButton",
            font=("Segoe UI Semibold", 11),
            padding=(20, 12),
            foreground="white",
            background=PRIMARY,
            borderwidth=0,
        )
        style.map("Primary.TButton", background=[("active", PRIMARY_DARK)])
        style.configure(
            "Secondary.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(16, 10),
            foreground=TEXT,
            background="#eef2f7",
            borderwidth=0,
        )
        style.map("Secondary.TButton", background=[("active", "#e2e8f0")])

    def _build(self):
        header = tk.Frame(self, bg=TEXT, height=92)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header, text="RENOMEADOR DE DOCUMENTOS",
            bg=TEXT, fg="white", font=("Segoe UI Semibold", 20)
        ).pack(anchor="w", padx=32, pady=(18, 0))
        tk.Label(
            header, text="Organize os documentos do funcionário sem precisar usar o terminal.",
            bg=TEXT, fg="#cbd5e1", font=("Segoe UI", 10)
        ).pack(anchor="w", padx=34, pady=(3, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=28, pady=22)

        # Indicador de etapas
        steps = tk.Frame(body, bg=BG)
        steps.pack(fill="x", pady=(0, 18))
        self.step_labels = []
        for i, label in enumerate(["1  Pasta", "2  Período", "3  Documentos", "4  Aguardar"]):
            lbl = tk.Label(
                steps, text=label, bg=BG, fg=MUTED,
                font=("Segoe UI Semibold", 10)
            )
            lbl.pack(side="left", padx=(0 if i == 0 else 24, 0))
            self.step_labels.append(lbl)

        self.content = tk.Frame(body, bg=BG)
        self.content.pack(fill="both", expand=True)

        self._show_step(1)

        footer = tk.Frame(self, bg="white", height=52)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Label(
            footer, textvariable=self.var_status,
            bg="white", fg=MUTED, font=("Segoe UI", 9)
        ).pack(side="left", padx=28, pady=16)
        tk.Label(
            footer, text=APP_VERSION,
            bg="white", fg="#9ca3af", font=("Segoe UI", 9)
        ).pack(side="right", padx=28)

    def _clear_content(self):
        if self.scan_animation_id is not None:
            try:
                self.after_cancel(self.scan_animation_id)
            except Exception:
                pass
            self.scan_animation_id = None
        self.scan_canvas = None
        for w in self.content.winfo_children():
            w.destroy()

    def _card(self, parent):
        frame = tk.Frame(
            parent, bg=CARD, highlightbackground=BORDER,
            highlightthickness=1, bd=0
        )
        return frame

    def _title(self, parent, title, subtitle=None):
        tk.Label(
            parent, text=title, bg=CARD, fg=TEXT,
            font=("Segoe UI Semibold", 19)
        ).pack(anchor="w", padx=28, pady=(25, 2))
        if subtitle:
            tk.Label(
                parent, text=subtitle, bg=CARD, fg=MUTED,
                font=("Segoe UI", 10), wraplength=780, justify="left"
            ).pack(anchor="w", padx=28, pady=(0, 20))

    def _button_row(self, parent):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=28, pady=(8, 26))
        return row

    def _show_step(self, step):
        self.var_step.set(step)
        self._clear_content()
        for i, lbl in enumerate(self.step_labels, 1):
            if i == step:
                lbl.configure(fg=PRIMARY)
            elif i < step:
                lbl.configure(fg=SUCCESS)
            else:
                lbl.configure(fg=MUTED)

        if step == 1:
            self._step_folder()
        elif step == 2:
            self._step_period()
        elif step == 3:
            self._step_documents()
        elif step == 4:
            self._step_waiting()

    # -------------------- PASSO 1 --------------------

    def _step_folder(self):
        card = self._card(self.content)
        card.pack(fill="x", pady=2)

        self._title(
            card,
            "Escolha a pasta do funcionário",
            "Comece selecionando a pasta onde ficam os documentos deste funcionário. "
            "Você não precisa copiar nenhum caminho."
        )

        select = tk.Frame(card, bg="#eff6ff")
        select.pack(fill="x", padx=28, pady=(0, 12))
        tk.Label(
            select, text="📁", bg="#eff6ff", fg=PRIMARY,
            font=("Segoe UI", 24)
        ).pack(side="left", padx=(18, 12), pady=16)

        info = tk.Frame(select, bg="#eff6ff")
        info.pack(side="left", fill="x", expand=True, pady=13)
        tk.Label(
            info, text="Pasta selecionada", bg="#eff6ff", fg=MUTED,
            font=("Segoe UI", 9)
        ).pack(anchor="w")
        tk.Label(
            info, textvariable=self.var_pasta, bg="#eff6ff", fg=TEXT,
            font=("Segoe UI Semibold", 10), anchor="w"
        ).pack(fill="x")

        ttk.Button(
            select, text="Selecionar pasta…",
            style="Primary.TButton", command=self._choose_folder
        ).pack(side="right", padx=16, pady=18)

        self.folder_result = tk.Frame(card, bg=CARD)
        self.folder_result.pack(fill="x", padx=28, pady=(2, 8))

        self._button_row(card)
        # Reobtém a linha para adicionar botão
        row = card.winfo_children()[-1]
        ttk.Button(
            row, text="Continuar →", style="Primary.TButton",
            command=self._to_period
        ).pack(side="right")

        tk.Label(
            card,
            text="💡 Dica: se você selecionar a pasta do ano (por exemplo, 2026), "
                 "o programa também reconhece automaticamente o funcionário.",
            bg=CARD, fg=MUTED, font=("Segoe UI", 9),
            wraplength=760, justify="left"
        ).pack(anchor="w", padx=28, pady=(0, 24))

        if self.pasta_funcionario:
            self._display_folder_result()

    def _choose_folder(self):
        initial = str(self.pasta_funcionario) if self.pasta_funcionario else os.path.expanduser("~")
        pasta = filedialog.askdirectory(
            title="Selecione a pasta do funcionário",
            initialdir=initial
        )
        if not pasta:
            return

        caminho = Path(pasta)
        ano_informado = None
        if re.fullmatch(r"\d{4}", caminho.name):
            ano_informado = caminho.name
            caminho = caminho.parent

        self.pasta_funcionario = caminho
        self.ano = ano_informado
        self.var_pasta.set(str(caminho))
        self.var_funcionario.set(nome_funcionario_sem_codigo(caminho.name))
        self.var_status.set("Pasta selecionada")
        self._display_folder_result()

    def _display_folder_result(self):
        for w in self.folder_result.winfo_children():
            w.destroy()

        tk.Label(
            self.folder_result, text="✓ Funcionário identificado",
            bg=CARD, fg=SUCCESS, font=("Segoe UI Semibold", 11)
        ).pack(anchor="w", pady=(6, 2))
        tk.Label(
            self.folder_result, text=self.var_funcionario.get(),
            bg=CARD, fg=TEXT, font=("Segoe UI Semibold", 14)
        ).pack(anchor="w", pady=(0, 3))

        if self.ano:
            tk.Label(
                self.folder_result,
                text=f"Ano encontrado no caminho: {self.ano}",
                bg=CARD, fg=MUTED, font=("Segoe UI", 9)
            ).pack(anchor="w")

    def _to_period(self):
        if not self.pasta_funcionario:
            messagebox.showwarning(
                "Pasta não selecionada",
                "Selecione primeiro a pasta do funcionário."
            )
            return
        self._show_step(2)

    # -------------------- PASSO 2 --------------------

    def _step_period(self):
        card = self._card(self.content)
        card.pack(fill="x", pady=2)
        self._title(
            card, "Escolha o período",
            f"Funcionário: {self.var_funcionario.get()}"
        )

        grid = tk.Frame(card, bg=CARD)
        grid.pack(fill="x", padx=28, pady=8)

        tk.Label(grid, text="ANO", bg=CARD, fg=MUTED,
                 font=("Segoe UI Semibold", 9)).grid(row=0, column=0, sticky="w", pady=(0, 5))
        tk.Label(grid, text="MÊS", bg=CARD, fg=MUTED,
                 font=("Segoe UI Semibold", 9)).grid(row=0, column=1, sticky="w", padx=(18, 0), pady=(0, 5))

        anos = listar_anos(self.pasta_funcionario)
        if self.ano and self.ano not in anos:
            anos.insert(0, self.ano)
        if not anos:
            anos = [str(__import__("datetime").date.today().year)]

        self.year_combo = ttk.Combobox(
            grid, textvariable=self.var_ano, values=anos,
            state="readonly", width=25
        )
        self.year_combo.grid(row=1, column=0, sticky="ew")
        if self.ano:
            self.var_ano.set(self.ano)
        else:
            self.var_ano.set(anos[0])

        meses = [f"{n:02d} — {MESES_UI[n].split('—', 1)[1].strip()}" for n in range(1, 13)]
        self.month_combo = ttk.Combobox(
            grid, textvariable=self.var_mes, values=meses,
            state="readonly", width=25
        )
        self.month_combo.grid(row=1, column=1, sticky="ew", padx=(18, 0))

        existentes = listar_meses_existentes(self.pasta_funcionario / self.var_ano.get())
        if existentes:
            self.var_mes.set(f"{existentes[0][0]:02d} — {MESES_UI[existentes[0][0]].split('—',1)[1].strip()}")
        else:
            import datetime
            self.var_mes.set(f"{datetime.date.today().month:02d} — {MESES_UI[datetime.date.today().month].split('—',1)[1].strip()}")

        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        hint = tk.Frame(card, bg="#f8fafc")
        hint.pack(fill="x", padx=28, pady=(22, 12))
        tk.Label(
            hint, text="O programa criará a pasta do ano/mês automaticamente se ela ainda não existir.",
            bg="#f8fafc", fg=MUTED, font=("Segoe UI", 9)
        ).pack(anchor="w", padx=15, pady=12)

        row = self._button_row(card)
        ttk.Button(
            row, text="← Voltar", style="Secondary.TButton",
            command=lambda: self._show_step(1)
        ).pack(side="left")
        ttk.Button(
            row, text="Continuar →", style="Primary.TButton",
            command=self._to_documents
        ).pack(side="right")

    def _to_documents(self):
        try:
            self.ano = self.var_ano.get().strip()
            self.numero_mes = int(self.var_mes.get().split("—", 1)[0].strip())
            if not re.fullmatch(r"\d{4}", self.ano):
                raise ValueError
        except Exception:
            messagebox.showwarning("Período inválido", "Selecione um ano e um mês válidos.")
            return

        try:
            self.pasta_destino = preparar_pasta_ano_mes(
                self.pasta_funcionario, self.ano, self.numero_mes
            )
        except Exception as erro:
            messagebox.showerror(
                "Não foi possível preparar a pasta",
                f"O programa não conseguiu criar/acessar a pasta do período.\n\nDetalhes: {erro}"
            )
            self.var_status.set("Erro ao preparar a pasta")
            return
        self._show_step(3)

    # -------------------- PASSO 3 --------------------

    def _step_documents(self):
        card = self._card(self.content)
        card.pack(fill="x", pady=2)
        self._title(
            card, "Configure os documentos",
            f"{self.var_funcionario.get()}  •  {MESES_UI[self.numero_mes]} / {self.ano}"
        )

        section = tk.Frame(card, bg=CARD)
        section.pack(fill="x", padx=28)

        tk.Label(
            section, text="Tipo do documento de ponto",
            bg=CARD, fg=TEXT, font=("Segoe UI Semibold", 11)
        ).pack(anchor="w", pady=(0, 7))

        ttk.Combobox(
            section, textvariable=self.var_tipo_ponto,
            values=list(TIPOS_PONTO_UI.keys()), state="readonly"
        ).pack(fill="x", pady=(0, 20))

        tk.Label(
            section, text="Quantidade de páginas",
            bg=CARD, fg=TEXT, font=("Segoe UI Semibold", 11)
        ).pack(anchor="w", pady=(0, 10))

        pages = tk.Frame(section, bg=CARD)
        pages.pack(fill="x")

        self._page_field(pages, "Espelho de ponto", self.var_espelho, 0)
        self._page_field(pages, "Documento de ponto", self.var_ponto, 1)
        self._page_field(pages, "Contracheque", self.var_contracheque, 2)

        self.total_label = tk.Label(
            card, text="", bg="#eff6ff", fg=PRIMARY,
            font=("Segoe UI Semibold", 11)
        )
        self.total_label.pack(fill="x", padx=28, pady=(20, 8))
        for var in (self.var_espelho, self.var_ponto, self.var_contracheque):
            var.trace_add("write", lambda *_: self._update_total())
        self._update_total()

        row = self._button_row(card)
        ttk.Button(
            row, text="← Voltar", style="Secondary.TButton",
            command=lambda: self._show_step(2)
        ).pack(side="left")
        ttk.Button(
            row, text="Revisar e iniciar →", style="Primary.TButton",
            command=self._review
        ).pack(side="right")

    def _page_field(self, parent, title, variable, col):
        box = tk.Frame(parent, bg="#f8fafc", highlightbackground=BORDER, highlightthickness=1)
        box.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
        parent.columnconfigure(col, weight=1)
        tk.Label(box, text=title, bg="#f8fafc", fg=MUTED,
                 font=("Segoe UI", 9), wraplength=170).pack(anchor="w", padx=13, pady=(12, 4))
        ttk.Entry(box, textvariable=variable, justify="center",
                  font=("Segoe UI Semibold", 14)).pack(fill="x", padx=12, pady=(0, 12))

    def _update_total(self):
        vals = []
        for var in (self.var_espelho, self.var_ponto, self.var_contracheque):
            try:
                vals.append(max(1, int(var.get())))
            except Exception:
                vals.append(0)
        total = sum(vals)
        self.total_label.configure(text=f"TOTAL DO PDF AGRUPADO: {total} página(s)")

    def _review(self):
        try:
            pe = int(self.var_espelho.get())
            pp = int(self.var_ponto.get())
            pc = int(self.var_contracheque.get())
            if min(pe, pp, pc) < 1:
                raise ValueError
        except Exception:
            messagebox.showwarning(
                "Quantidade inválida",
                "Informe pelo menos 1 página para cada documento."
            )
            return

        tipo = TIPOS_PONTO_UI[self.var_tipo_ponto.get()]
        self.configuracao = {
            "tipo_ponto": tipo,
            "paginas_espelho": pe,
            "paginas_ponto": pp,
            "paginas_contracheque": pc,
            "total_paginas": pe + pp + pc,
        }

        self._start_monitoring()

    # -------------------- PASSO 4 --------------------

    def _step_waiting(self):
        card = self._card(self.content)
        card.pack(fill="x", pady=2)

        self._title(
            card, "Pronto para digitalizar",
            "Coloque o PDF agrupado na pasta de entrada. A separação começa automaticamente."
        )

        status = tk.Frame(card, bg="#f0fdf4")
        status.pack(fill="x", padx=28, pady=(0, 16))

        self.status_icon = tk.Label(
            status, text="●", bg="#f0fdf4", fg=SUCCESS,
            font=("Segoe UI", 22)
        )
        self.status_icon.pack(side="left", padx=(18, 10), pady=18)

        self.status_text = tk.Label(
            status, text="Aguardando PDF…", bg="#f0fdf4", fg=TEXT,
            font=("Segoe UI Semibold", 12)
        )
        self.status_text.pack(side="left")

        self.error_panel = tk.Frame(card, bg="#fef2f2", highlightbackground="#fecaca", highlightthickness=1)
        self.error_title = tk.Label(
            self.error_panel, text="ERRO — PROCESSAMENTO INTERROMPIDO",
            bg="#fef2f2", fg="#b91c1c", font=("Segoe UI Semibold", 11), anchor="w"
        )
        self.error_title.pack(fill="x", padx=14, pady=(12, 4))
        self.error_message = tk.Label(
            self.error_panel, text="", bg="#fef2f2", fg="#7f1d1d",
            font=("Segoe UI", 10), anchor="w", justify="left", wraplength=760
        )
        self.error_message.pack(fill="x", padx=14, pady=(0, 12))
        self.error_panel.pack(fill="x", padx=28, pady=(0, 14))
        self.error_panel.pack_forget()

        self.scan_canvas = tk.Canvas(
            card, height=112, bg="#f8fafc", highlightthickness=0, bd=0
        )
        self.scan_canvas.pack(fill="x", padx=28, pady=(0, 14))
        self.scan_active = False
        self._draw_scan_animation()

        info = tk.Frame(card, bg=CARD)
        info.pack(fill="x", padx=28)

        items = [
            ("Funcionário", self.var_funcionario.get()),
            ("Período", f"{MESES_UI[self.numero_mes]} / {self.ano}"),
            ("Total esperado", f"{self.configuracao['total_paginas']} páginas"),
            ("Pasta de entrada", str(Path(__file__).resolve().parent)),
            ("Destino", str(self.pasta_destino)),
        ]

        for label, value in items:
            row = tk.Frame(info, bg=CARD)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, bg=CARD, fg=MUTED,
                     font=("Segoe UI", 9), width=19, anchor="w").pack(side="left")
            tk.Label(row, text=value, bg=CARD, fg=TEXT,
                     font=("Segoe UI Semibold", 9), anchor="w").pack(side="left", fill="x")

        order = tk.Frame(card, bg="#f8fafc")
        order.pack(fill="x", padx=28, pady=(20, 10))
        tk.Label(order, text="LEMBRETE — ORDEM CORRETA DO ESCANEAMENTO",
                 bg="#f8fafc", fg=PRIMARY,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=15, pady=(12, 5))
        tipo = self.var_tipo_ponto.get()
        for numero, nome in [("1", "Espelho de ponto"), ("2", tipo), ("3", "Contracheque")]:
            linha = tk.Frame(order, bg="#f8fafc")
            linha.pack(anchor="w", fill="x", padx=15, pady=3)
            tk.Label(linha, text=f"  {numero}  ", bg=PRIMARY, fg="white",
                     font=("Segoe UI Semibold", 9), padx=3, pady=2).pack(side="left")
            tk.Label(linha, text=nome, bg="#f8fafc", fg=TEXT,
                     font=("Segoe UI Semibold", 10)).pack(side="left", padx=9)
        tk.Label(order, text="Mantenha essa sequência no PDF para que cada documento seja separado corretamente.",
                 bg="#f8fafc", fg=MUTED, font=("Segoe UI", 9),
                 wraplength=740, justify="left").pack(anchor="w", padx=15, pady=(7, 13))

        row = self._button_row(card)
        ttk.Button(
            row, text="Parar e configurar novamente",
            style="Secondary.TButton", command=self._stop_and_reset
        ).pack(side="left")

    def _draw_scan_animation(self):
        """Desenha uma animação leve de digitalização no painel."""
        canvas = self.scan_canvas
        if canvas is None or not canvas.winfo_exists():
            return

        canvas.delete("all")
        largura = max(canvas.winfo_width(), 600)
        altura = 112
        canvas.configure(height=altura)
        canvas.create_rectangle(0, 0, largura, altura, fill="#f8fafc", outline="")

        cx, cy = largura * 0.24, 55
        canvas.create_rectangle(cx - 39, cy - 32, cx + 28, cy + 34,
                                fill="#dbeafe", outline="#bfdbfe", width=1)
        canvas.create_rectangle(cx - 31, cy - 37, cx + 36, cy + 29,
                                fill="#eff6ff", outline="#93c5fd", width=1)
        canvas.create_rectangle(cx - 23, cy - 42, cx + 44, cy + 24,
                                fill="white", outline="#60a5fa", width=2)
        for j in range(3):
            y = cy - 26 + j * 12
            canvas.create_line(cx - 11, y, cx + 31, y, fill="#cbd5e1", width=2)

        if self.scan_active:
            laser_x = cx - 22 + (self.scan_phase % 58)
            canvas.create_line(laser_x, cy - 43, laser_x, cy + 25,
                               fill="#2563eb", width=3)
            canvas.create_oval(laser_x - 5, cy - 46, laser_x + 5, cy - 36,
                               fill="#60a5fa", outline="")
        else:
            canvas.create_line(cx - 20, cy - 10, cx + 40, cy - 10,
                               fill="#bfdbfe", width=2)

        canvas.create_text(largura * 0.42, 37, anchor="w",
                           text="LEITURA INTELIGENTE DE DOCUMENTOS",
                           fill="#64748b", font=("Segoe UI Semibold", 9))
        texto = ("Analisando páginas e separando os arquivos…" if self.scan_active
                 else "Aguardando o PDF para iniciar automaticamente")
        canvas.create_text(largura * 0.42, 60, anchor="w",
                           text=texto, fill="#172033",
                           font=("Segoe UI Semibold", 11))
        canvas.create_text(largura * 0.42, 81, anchor="w",
                           text="O PDF original é removido somente após a separação bem-sucedida.",
                           fill="#64748b", font=("Segoe UI", 9))

        self.scan_phase = (self.scan_phase + 4) % 58
        self.scan_animation_id = self.after(70, self._draw_scan_animation)

    def _handle_worker_event(self, tipo, detalhe=None):
        self.events.put((tipo, detalhe))

    def _show_processing_error(self, message):
        """Interrompe o monitoramento e mostra o erro dentro da janela principal."""
        self.running = False
        self.scan_active = False
        self.var_status.set("Erro — processamento interrompido")
        if hasattr(self, "status_text") and self.status_text.winfo_exists():
            self.status_text.configure(text="O processamento foi interrompido. Leia o erro abaixo.")
        if hasattr(self, "status_icon") and self.status_icon.winfo_exists():
            self.status_icon.configure(fg="#dc2626")
        if hasattr(self, "error_message") and self.error_message.winfo_exists():
            self.error_message.configure(text=str(message))
            self.error_panel.pack(fill="x", padx=28, pady=(0, 14), before=self.scan_canvas)
        self._draw_scan_animation()

    def _open_destination_folder(self, caminho):
        try:
            pasta = str(Path(caminho).resolve())
            if os.name == "nt":
                os.startfile(pasta)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", pasta])
            else:
                subprocess.Popen(["xdg-open", pasta])
        except Exception as erro:
            self.events.put(("open_error", f"Não foi possível abrir a pasta de destino: {erro}"))

    def _reset_after_separation(self, pasta_destino):
        self.running = False
        self.scan_active = False
        self._open_destination_folder(pasta_destino)

        self.pasta_funcionario = None
        self.ano = None
        self.numero_mes = None
        self.pasta_destino = None
        self.configuracao = None
        self.var_pasta.set("Nenhuma pasta selecionada")
        self.var_funcionario.set("—")
        self.var_ano.set("")
        self.var_mes.set("")
        self.var_status.set("Separação concluída — selecione outro funcionário")
        self._show_step(1)

    def _start_monitoring(self):
        self.running = True
        self.var_status.set("Monitorando a pasta de entrada…")
        self._show_step(4)
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def _worker(self):
        pasta_origem = Path(__file__).resolve().parent
        try:
            # A função original bloqueia até encontrar um PDF.
            processar_pdfs(
                pasta_origem,
                self.pasta_destino,
                nome_funcionario_sem_codigo(self.pasta_funcionario.name),
                self.ano,
                self.numero_mes,
                self.configuracao,
                notificar=self._handle_worker_event,
            )
            self.events.put(("done", "Monitoramento encerrado."))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _poll_events(self):
        try:
            while True:
                kind, message = self.events.get_nowait()
                if kind == "scan":
                    self.scan_active = True
                    self.var_status.set("PDF detectado — iniciando leitura…")
                    if hasattr(self, "status_text") and self.status_text.winfo_exists():
                        self.status_text.configure(text=message or "Digitalizando e separando…")
                    if hasattr(self, "status_icon") and self.status_icon.winfo_exists():
                        self.status_icon.configure(fg=PRIMARY)
                elif kind == "progress":
                    if hasattr(self, "status_text") and self.status_text.winfo_exists():
                        self.status_text.configure(text=message[2] if isinstance(message, tuple) else str(message))
                    self.var_status.set("Separando documentos…")
                elif kind == "page":
                    if hasattr(self, "status_text") and self.status_text.winfo_exists():
                        self.status_text.configure(text=message[2])
                elif kind == "waiting":
                    self.scan_active = False
                    self.var_status.set("Aguardando correção do PDF")
                    if hasattr(self, "status_text") and self.status_text.winfo_exists():
                        self.status_text.configure(text=message)
                    if hasattr(self, "status_icon") and self.status_icon.winfo_exists():
                        self.status_icon.configure(fg=WARNING)
                elif kind == "separated":
                    self.scan_active = False
                    self._reset_after_separation(message)
                elif kind == "open_error":
                    messagebox.showwarning("Pasta de destino", message)
                elif kind == "done":
                    if self.running:
                        self.var_status.set("Monitoramento encerrado")
                elif kind == "error":
                    self._show_processing_error(message)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _stop_and_reset(self):
        # O processamento original é cooperativo somente entre PDFs.
        # Encerrar a janela continua sendo seguro; para uma nova configuração,
        # marcamos a tela como pronta e o usuário pode iniciar outra sessão.
        self.running = False
        self.var_status.set("Pronto para começar")
        self._show_step(1)

    def destroy(self):
        self.running = False
        super().destroy()



def _version_tuple(tag):
    """Converte tags como v17.2.1 em uma tupla comparável."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(tag))
    if not match:
        match = re.search(r"(\d+)", str(tag))
        return (int(match.group(1)), 0, 0) if match else (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _mostrar_janela_atualizacao():
    janela = tk.Tk()
    janela.title("Renomeador de Documentos — Atualização")
    janela.geometry("470x170")
    janela.resizable(False, False)
    janela.configure(bg=BG)
    janela.protocol("WM_DELETE_WINDOW", lambda: None)
    tk.Label(
        janela, text="Atualização disponível", bg=BG, fg=TEXT,
        font=("Segoe UI Semibold", 15)
    ).pack(anchor="w", padx=24, pady=(20, 4))
    status = tk.Label(
        janela, text="Preparando o download…", bg=BG, fg=MUTED,
        font=("Segoe UI", 10)
    )
    status.pack(anchor="w", padx=24, pady=(0, 12))
    barra = ttk.Progressbar(janela, mode="determinate", maximum=100, length=420)
    barra.pack(padx=24, fill="x")
    janela.update_idletasks()
    return janela, status, barra


def check_for_updates():
    """Atualiza o executável a partir do GitHub Releases, sem bloquear falhas de rede."""
    # A atualização automática é destinada à versão .exe distribuída aos funcionários.
    if not getattr(sys, "frozen", False):
        return

    repo_api = "https://api.github.com/repos/davi-souza-vmg/Phytons/releases?per_page=100"
    try:
        req = urllib.request.Request(
            repo_api,
            headers={"User-Agent": "Renomeador-de-Documentos-Updater", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            releases = json.loads(response.read().decode("utf-8"))
    except Exception:
        # Sem internet, GitHub indisponível ou ainda sem Release: abre a cópia local.
        return

    # Este aplicativo usa tags próprias para não confundir suas versões com
    # Releases de outros sistemas publicados no mesmo repositório-hub.
    releases_renomeador = [
        item for item in releases
        if isinstance(item, dict)
        and not item.get("draft", False)
        and not item.get("prerelease", False)
        and str(item.get("tag_name", "")).startswith("renomeador-v")
    ]
    release = max(
        releases_renomeador,
        key=lambda item: _version_tuple(item.get("tag_name", "")),
        default=None,
    )
    if release is None:
        return

    latest_tag = str(release.get("tag_name", "")).strip()
    if not latest_tag or _version_tuple(latest_tag) <= _version_tuple(APP_VERSION):
        return

    asset_name = "Renomeador-de-Documentos.exe"
    asset = next((a for a in release.get("assets", []) if a.get("name") == asset_name), None)
    if not asset or not asset.get("browser_download_url"):
        return

    janela = status = barra = None
    temporario = Path(tempfile.gettempdir()) / f"Renomeador-atualizacao-{os.getpid()}.exe"
    try:
        janela, status, barra = _mostrar_janela_atualizacao()
        status.configure(text=f"Baixando a versão {latest_tag}…")
        req = urllib.request.Request(
            asset["browser_download_url"],
            headers={"User-Agent": "Renomeador-de-Documentos-Updater"},
        )
        with urllib.request.urlopen(req, timeout=30) as response, temporario.open("wb") as destino:
            total = int(response.headers.get("Content-Length", "0") or 0)
            baixado = 0
            while True:
                bloco = response.read(1024 * 256)
                if not bloco:
                    break
                destino.write(bloco)
                baixado += len(bloco)
                if total > 0:
                    percentual = min(100, int(baixado * 100 / total))
                    barra.configure(value=percentual)
                    status.configure(text=f"Baixando a versão {latest_tag}… {percentual}%")
                else:
                    status.configure(text=f"Baixando a versão {latest_tag}… ({baixado // (1024 * 1024)} MB)")
                janela.update_idletasks()
                janela.update()

        if not temporario.exists() or temporario.stat().st_size < 1_000_000:
            raise RuntimeError("O executável baixado está incompleto.")
        with temporario.open("rb") as arquivo:
            if arquivo.read(2) != b"MZ":
                raise RuntimeError("O arquivo baixado não parece ser um executável Windows válido.")

        digest = asset.get("digest", "")
        if digest.startswith("sha256:"):
            sha = hashlib.sha256(temporario.read_bytes()).hexdigest()
            if sha.lower() != digest.split(":", 1)[1].lower():
                raise RuntimeError("A verificação de integridade do download falhou.")

        destino_final = Path(sys.executable).resolve()
        script_ps = Path(tempfile.gettempdir()) / f"Renomeador-atualizador-{os.getpid()}.ps1"
        script_ps.write_text(
            "param([int]$OldPid, [string]$Downloaded, [string]$Target)\n"
            "$ErrorActionPreference = 'Stop'\n"
            "while (Get-Process -Id $OldPid -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 500 }\n"
            "try { Copy-Item -LiteralPath $Downloaded -Destination $Target -Force; Start-Process -FilePath $Target }\n"
            "catch { try { Start-Process -FilePath $Target } catch {} }\n"
            "finally { Remove-Item -LiteralPath $Downloaded -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue }\n",
            encoding="utf-8",
        )
        status.configure(text="Download concluído. Reiniciando com a nova versão…")
        barra.configure(value=100)
        janela.update_idletasks()
        subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(script_ps), str(os.getpid()), str(temporario), str(destino_final),
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        janela.destroy()
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as erro:
        try:
            if janela is not None and janela.winfo_exists():
                janela.destroy()
        except Exception:
            pass
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning(
                "Atualização não concluída",
                f"Não foi possível instalar a versão {latest_tag}.\n\n"
                f"O programa tentará abrir a versão atual.\n\nDetalhes: {erro}",
                parent=root,
            )
            root.destroy()
        except Exception:
            pass
        try:
            temporario.unlink(missing_ok=True)
        except Exception:
            pass


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    check_for_updates()
    main()
