# Base historica permanente

Esta estrutura guarda os extratos do banco, os relatorios do sistema, os lancamentos importados e as execucoes de conciliacao. A ideia e parar de trabalhar arquivo por arquivo solto e montar um historico consultavel.

## Pastas

- `C:\ConciliaFinanceira\entrada\banco`: coloque aqui PDFs ou CSVs do banco.
- `C:\ConciliaFinanceira\entrada\sistema`: coloque aqui XLS ou XLSX do sistema.
- `C:\ConciliaFinanceira\processados\banco`: copia arquivada dos arquivos bancarios ja importados.
- `C:\ConciliaFinanceira\processados\sistema`: copia arquivada dos arquivos do sistema ja importados.
- `C:\ConciliaFinanceira\dados\extracoes`: CSVs extraidos automaticamente dos PDFs.
- pasta oficial de rede cadastrada localmente em `C:\ConciliaFinanceira\config_pastas.json` para leitura dos extratos bancarios em PDF.

## Primeiro uso

Execute uma vez:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\aplicar_migracao_historico.py
```

## Importar novos arquivos

Coloque os arquivos nas pastas de entrada e execute:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\atualizar_base.py
```

Tambem da para importar arquivos especificos:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\importar_historico.py --banco C:\CAMINHO\BANCO.pdf --sistema C:\CAMINHO\SISTEMA.xls
```

Se o mesmo arquivo for importado novamente, o sistema reconhece pelo hash e nao duplica os lancamentos.

## Importar direto do Clinux/Genesis

Com o Clinux aberto no computador, ele cria um tunel local para o banco PostgreSQL do sistema. Para importar os lancamentos financeiros do Clinux para a base local:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\importar_clinux_sistema.py --inicio 2024-01-01 --fim 2026-12-31
```

Para substituir os dados antigos importados do `SISTEMA.xls`:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\importar_clinux_sistema.py --inicio 2024-01-01 --fim 2026-12-31 --substituir-sistema-xls
```

A origem gravada em `lancamentos_sistema` passa a ser `CLINUX`.

Para importar todas as unidades e substituir uma importacao anterior do Clinux:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\importar_clinux_sistema.py --inicio 2024-01-01 --fim 2026-12-31 --todas-empresas --substituir-clinux --substituir-sistema-xls
```

Regras atuais:

- `CLINUX`: pagamentos realizados vindos de `public.pagamentos` e `public.lancamentos`.
- `CLINUX_TRANSFERENCIA`: transferencias entre contas vindas de `public.bancos_transfere`.
- O tipo entrada/saida usa `contas_grupos.sn_despesa`: grupos marcados como despesa viram `SAIDA`; grupos nao marcados como despesa viram `ENTRADA`.
- Faturamento bruto deve considerar entradas de `CLINUX` no grupo `RECEITAS`, excluindo `CLINUX_TRANSFERENCIA`.

Para ver o faturamento bruto e movimentacoes por unidade:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\resumo_clinux_local_por_unidade.py
```

## Conciliar um periodo

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\conciliar_periodo.py --inicio 2026-06-01 --fim 2026-06-30
```

Esse comando usa a base historica, aplica as regras atuais de conciliacao e registra uma execucao em `conciliacao_execucoes`.

## Consultar o que ja esta guardado

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\consultar_base_historica.py
```

Ele mostra arquivos importados por origem, periodo coberto, totais do banco, totais do sistema e as ultimas conciliacoes registradas.

## Atualizacao incremental

Use este comando unico para atualizar a base:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\atualizar_base.py
```

Ou execute:

```text
C:\ConciliaFinanceira\atualizar_base.bat
```

O comando faz duas coisas:

- importa arquivos novos em `entrada\banco` e `entrada\sistema`;
- busca no Clinux/Genesis apenas pagamentos e transferencias com IDs maiores que os ja gravados na base local.
- se o Clinux estiver fechado, tenta abrir um tunel SSH proprio usando a configuracao autorizada do `clinux.ini`.

Para atualizar somente os arquivos das pastas:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\atualizar_base.py --sem-clinux
```

Para conferir a pasta de rede sem importar nada:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\atualizar_base.py --sem-clinux --listar-arquivos
```

A pasta de rede esta conectada, mas ficou marcada como `ativo: false` enquanto terminamos a deduplicacao de extratos sobrepostos. A regra atual lista PDFs com extensao `.pdf` na pasta oficial de bancos, com leitura deduplicada na importacao.

## Leitores de PDF bancario

Os leitores especificos ficam em `C:\ConciliaFinanceira\python\leitores_pdf_banco.py`.

Layouts ja tratados:

- Cora: extrato de conta com bloco `Transacoes`.
- Bradesco: extrato mensal/por periodo do Net Empresa.
- Banco do Brasil: extrato de conta corrente.
- Caixa: Gerenciador Caixa, extrato por periodo e layout novo com valor em linha quebrada.
- Banco da Amazonia/BASA: Amazonia Online.
- Sicoob: SISBR, extrato conta corrente.
- Safra: extrato de movimentacao.
- Stone: extrato de conta corrente.
- Itau: conta corrente com texto nativo e fallback por OCR para PDFs antigos em imagem.
- Banco do Nordeste/BNB: conta corrente.
- Unicred: conta corrente em layouts antigo e novo.
- Uniprime: conta corrente.
- Clinux/Genesis: `Extrato Banco Usuario`, identificado com aviso porque e relatorio do sistema, nao extrato oficial do banco.

Layouts identificados, mas sem importacao transacional:

- BNB consolidado/aplicacao: demonstrativo/resumo de investimento sem lancamentos de conta corrente.
- Unicred aplicacao/rentabilidade: demonstrativo de rentabilidade sem lancamentos de conta corrente.
- PDFs sem texto extraivel: usa OCR quando o Tesseract estiver instalado em `C:\Program Files\Tesseract-OCR\tesseract.exe`.

Para validar uma amostra por banco:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\validar_leitores_pdf_bancos.py
```

Para inventariar todos os PDFs oficiais da pasta de bancos:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\inventariar_pdfs_bancos_extratos.py --workers 4
```

O inventario completo grava primeiro em `inventario_pdfs_bancos_extratos.em_execucao.csv` e so substitui `inventario_pdfs_bancos_extratos.csv` quando a rede nao apresenta erro massivo de arquivo inacessivel.

Para atualizar somente o Clinux/Genesis:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\atualizar_base.py --somente-clinux
```

## Observacao importante

Os arquivos brutos dos ultimos 12 meses continuam guardados em `processados`. O banco de dados guarda os lancamentos estruturados, e a pasta de rede oficial permanece como fonte para reprocessamento quando necessario.
