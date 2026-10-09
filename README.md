# Phytons — hub de sistemas

Este repositório pode reunir vários sistemas. Cada aplicativo deve ficar em sua própria pasta dentro de `apps/`, com seu próprio fluxo de publicação e prefixo de tag.

## Estrutura sugerida

```text
Phytons/
├── README.md
├── apps/
│   └── renomeador/
│       ├── renomeador_documentos.py
│       └── requirements.txt
└── .github/
    └── workflows/
        └── release-renomeador.yml
```

## Publicar o Renomeador pela primeira vez

1. Faça upload de todos os arquivos/pastas deste pacote para a raiz do repositório `davi-souza-vmg/Phytons`, mantendo exatamente a estrutura acima.
2. No GitHub, abra **Settings → Actions → General → Workflow permissions**. Se aparecer a opção de permissões, selecione **Read and write permissions** e salve. O workflow declara `contents: write` para anexar o executável à Release.
3. Abra **Releases → Draft a new release**.
4. No campo da tag, crie `renomeador-v17.0.0`. Escolha a branch principal como destino da tag.
5. Use o título `Renomeador de Documentos v17.0.0` e clique em **Publish release**.
6. Abra a aba **Actions** e entre na execução `Compilar e publicar Renomeador de Documentos`. Aguarde ficar verde/concluída.
7. Volte à Release `renomeador-v17.0.0`. Baixe `Renomeador-de-Documentos.exe` e teste primeiro em uma pasta de teste.
8. Coloque o `.exe` na Área de Trabalho. Quando publicar uma nova versão do Renomeador, crie uma tag crescente, por exemplo `renomeador-v17.0.1` ou `renomeador-v18.0.0`.

## Regra importante para o repositório-hub

**Não use tags genéricas como `v18.0.0` para todos os aplicativos.** Cada aplicativo precisa de um prefixo próprio, por exemplo:

- Renomeador: `renomeador-v17.0.0`
- Painel de Condutores: `condutores-v1.0.0`
- Outro sistema: `nomedosistema-v1.0.0`

O atualizador do Renomeador consulta apenas Releases com tags `renomeador-v...`; assim, uma Release de outro sistema não fará o Renomeador baixar o executável errado. Cada novo aplicativo deve ter seu próprio workflow de compilação e atualização que filtre o prefixo correspondente.

## Atualização automática

O `.exe` consulta Releases públicas do repositório e seleciona a versão mais recente com tag `renomeador-v...`. Só baixa se a versão remota for superior à local. Se a internet/GitHub estiver indisponível ou não houver Release do Renomeador, tenta abrir a versão local. O mecanismo de atualização está ativo no executável empacotado; executar o `.py` diretamente não faz autoatualização.

## Cuidados

- O GitHub distribui o programa; documentos PDF e dados de funcionários não devem ser enviados ao repositório.
- O primeiro `.exe` só existirá depois de publicar a primeira Release e a compilação terminar com sucesso.
- Teste em PDFs de exemplo antes de processar documentos oficiais.
- O Windows pode exibir alerta SmartScreen para executáveis não assinados.
- Mantenha as permissões do repositório e as credenciais do GitHub protegidas.
