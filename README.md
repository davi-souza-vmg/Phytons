# Renomeador de Documentos — distribuição com atualização automática

Este pacote prepara o repositório `davi-souza-vmg/Phytons` para compilar o Renomeador como `.exe` no GitHub Actions e publicar o executável em GitHub Releases.

## Arquivos

- `renomeador_documentos.py`: aplicativo baseado na versão v17, com verificação automática de atualização para a versão empacotada como `.exe`.
- `.github/workflows/release.yml`: compila o executável no Windows e publica o `.exe` e seu checksum quando uma tag `v*` é enviada ao GitHub.
- `requirements.txt`: dependência usada pelo aplicativo.

## Como colocar no repositório

1. Baixe e extraia este ZIP.
2. Envie todos os arquivos e a pasta `.github/workflows` para a raiz do repositório `Phytons`, substituindo o README antigo se quiser usar o README deste pacote.
3. No GitHub, abra **Settings → Actions → General → Workflow permissions** e confirme que os workflows podem ter permissão de escrita no repositório, se essa opção estiver disponível. O workflow declara `contents: write`.
4. Abra **Releases → Draft a new release**. Crie uma nova tag `v17.0.0`, escreva um título e publique a Release. Para versões seguintes, use tags crescentes, como `v17.0.1` ou `v18.0.0`.
5. Acompanhe **Actions**. O workflow compila o executável no Windows e adiciona `Renomeador-de-Documentos.exe` e `SHA256SUMS.txt` à Release que você publicou.
6. Quando o workflow terminar, baixe o `.exe` na página **Releases** e coloque-o na Área de Trabalho dos funcionários.

## Atualizações automáticas

Na inicialização, o executável consulta a última Release pública. Se a versão da Release for superior à versão local, baixa o `.exe`, verifica se é um executável válido e, quando o GitHub fornece o digest SHA-256, confere a integridade antes de substituir a cópia local e reiniciá-la. Se a consulta falhar ou não houver Release disponível, tenta abrir a versão local normalmente.

O aplicativo em execução como `.py` não se autoatualiza; esse mecanismo é ativado no `.exe` publicado pelo workflow.

## Importante

- O GitHub distribui apenas o programa; os PDFs permanecem no computador do usuário.
- O primeiro `.exe` precisa ser publicado em uma Release antes de o atualizador conseguir encontrar uma versão remota.
- A substituição automática funciona melhor quando o `.exe` está em uma pasta em que o funcionário tem permissão de gravação, como a Área de Trabalho.
- O Windows SmartScreen pode exibir um aviso para executáveis novos ou não assinados. Para distribuição corporativa, considere assinatura digital do executável.
- Faça um teste com PDFs de exemplo antes de utilizar documentos oficiais.
