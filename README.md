# Renomeador de Documentos — DP

Aplicativo Windows com inicializador que consulta as GitHub Releases públicas e baixa o aplicativo quando a versão local é diferente da última versão estável.

## Como publicar

1. Envie `renomeador_documentos.py`, `launcher.py`, `requirements.txt`, este `README.md` e `.github/workflows/release-windows.yml` para a raiz do repositório `davi-souza-vmg/Phytons`.
2. No GitHub, abra **Settings → Actions → General** e confirme que Actions está habilitado e que o workflow tem permissão para criar releases (o workflow solicita `contents: write`).
3. Crie e envie uma tag de versão, por exemplo `v18`. O workflow compilará os dois `.exe` em um runner Windows e anexará `Renomeador.exe` e `RenomeadorApp.exe` à Release.
4. Baixe `Renomeador.exe` da Release publicada e coloque-o na Área de Trabalho dos funcionários. Eles devem iniciar o programa por esse arquivo.

## Próximas versões

Edite o código, envie as alterações para `main` e publique uma nova tag, por exemplo `v19`. Na próxima abertura do inicializador, a versão mais recente será baixada automaticamente. Se a versão local já for a mais recente, o executável do aplicativo não será baixado de novo.

## Observações

- O repositório e as Releases precisam ser públicos para este fluxo sem autenticação.
- O inicializador fica estável e baixa versões do aplicativo para `%LOCALAPPDATA%\RenomeadorDP\versions`.
- Os PDFs são processados localmente na pasta onde `Renomeador.exe` está instalado; não são enviados ao GitHub.
- Se o GitHub estiver indisponível, o inicializador tenta abrir a última versão de aplicativo que já foi baixada.
- O primeiro uso exige internet e uma Release publicada com `RenomeadorApp.exe`.
- O workflow compila os executáveis no Windows. Este pacote contém as fontes e a automação de compilação; não contém um `.exe` já compilado.
