# Instalação e Configuração do SmartTraderEA

Este guia leva você do **zero** até o robô (Expert Advisor, ou "EA") rodando
em uma **conta demo** (dinheiro de mentira) dentro do MetaTrader 4. É feito
para quem nunca usou o MT4. Faça cada passo na ordem.

> ⚠️ **Leia primeiro:** trading envolve risco real de perda. Você vai começar
> em conta **demo**, com dinheiro fictício, justamente para aprender sem
> arriscar nada. Só pense em dinheiro real muito depois, e só depois de ler a
> seção de [Segurança](#9-avisos-de-segurança-leia-com-atenção).

---

## Índice
1. [O que você vai precisar](#1-o-que-você-vai-precisar)
2. [Baixar e instalar o MetaTrader 4](#2-baixar-e-instalar-o-metatrader-4)
3. [Abrir uma conta DEMO](#3-abrir-uma-conta-demo-dinheiro-fake)
4. [Achar a Pasta de Dados do MT4](#4-achar-a-pasta-de-dados-do-mt4)
5. [Copiar os arquivos do bot](#5-copiar-os-arquivos-do-bot)
6. [Compilar no MetaEditor (F7)](#6-compilar-no-metaeditor-f7)
7. [Anexar o EA ao gráfico e ligar o AutoTrading](#7-anexar-o-ea-ao-gráfico-e-ligar-o-autotrading)
8. [Configurar os inputs do EA](#8-configurar-os-inputs-do-ea)
9. [Avisos de segurança](#9-avisos-de-segurança-leia-com-atenção)
10. [Ligar a camada de IA (opcional)](#10-ligar-a-camada-de-ia-opcional)

---

## 1. O que você vai precisar

- Um computador **Windows** (o MT4 é nativo de Windows; em Mac/Linux roda via
  Wine ou máquina virtual, mas o caminho mais simples é Windows).
- Conexão com a internet.
- Os arquivos deste projeto (a pasta `mql4/` com o EA e os includes).
- Cerca de 30 minutos.

---

## 2. Baixar e instalar o MetaTrader 4

O MT4 é distribuído pelas **corretoras** (brokers). Você baixa o instalador da
corretora onde vai abrir a conta demo. Algumas opções comuns que oferecem MT4
e contas demo gratuitas: **XM, Exness, IC Markets, Pepperstone, FBS, Tickmill**
(entre muitas outras). Qualquer uma serve para testar em demo.

**Passos:**

1. Entre no site da corretora escolhida e procure por **"MetaTrader 4"** ou
   **"Plataformas"** > **"MT4"** > **"Download para PC / Windows"**.
2. Baixe o instalador (geralmente um arquivo `.exe`, algo como
   `corretora4setup.exe`).
3. Execute o instalador, aceite os termos e clique em **Avançar / Instalar**.
4. Ao final, o MT4 abre sozinho. Ele pode pedir para escolher um servidor de
   conta — isso é o próximo passo.

> 💡 Você também pode baixar o MT4 genérico pela **MetaQuotes**, mas baixar
> pela própria corretora já deixa os servidores dela pré-configurados, o que
> facilita abrir a conta demo.

---

## 3. Abrir uma conta DEMO (dinheiro fake)

Uma conta **demo** usa dinheiro fictício, mas com **preços reais de mercado**.
É o ambiente perfeito para aprender e validar o bot sem risco.

**Dentro do MT4:**

1. Menu **Arquivo** (*File*) > **Abrir uma conta** (*Open an Account*).
2. Selecione a corretora/servidor da lista (se baixou pela corretora, já
   aparece). Clique em **Avançar**.
3. Marque a opção **"Nova conta de demonstração"** (*New demo account*) e
   clique em **Avançar**.
4. Preencha o formulário:
   - **Nome, e-mail, telefone** (pode ser real; serve só para a corretora).
   - **Tipo de conta** (*Account type*): escolha algo padrão (ex.: "Standard").
   - **Depósito** (*Deposit*): valor fictício. **Recomendado: 1000 a 10000 USD**
     — um valor parecido com o que você usaria de verdade, para os testes
     fazerem sentido.
   - **Alavancagem** (*Leverage*): para iniciante, prefira algo **conservador**
     como **1:30 ou 1:100**. Alavancagem muito alta (1:500+) amplifica perdas.
5. Aceite os termos e clique em **Avançar / Concluir**.
6. O MT4 mostra **login, senha e servidor**. **Anote isso** — você usa para
   logar de novo depois.

Pronto: no canto superior você verá o **número da conta** e o saldo fictício.
A janela **"Observação do Mercado"** (*Market Watch*) lista os símbolos
(EURUSD, etc.). Se estiver vazia, clique com o botão direito nela >
**"Mostrar tudo"** (*Show All*).

---

## 4. Achar a Pasta de Dados do MT4

O MT4 não guarda os robôs na pasta onde foi instalado, e sim numa **Pasta de
Dados** separada (por causa das permissões do Windows). É lá que vamos colocar
os arquivos do bot.

1. No MT4, vá em **Arquivo** (*File*) > **Abrir Pasta de Dados**
   (*Open Data Folder*).
2. Abre uma janela do Windows Explorer. Dentro dela, entre na pasta **`MQL4`**.
3. Dentro de `MQL4` você verá várias subpastas. As duas que importam:

| Pasta | O que vai aqui |
|-------|----------------|
| `MQL4\Experts` | O robô: `SmartTraderEA.mq4` |
| `MQL4\Include` | Os módulos: `Indicators.mqh`, `RiskManager.mqh`, `AIBridge.mqh` |

> 💡 Deixe essa janela aberta — você vai usá-la no próximo passo.

---

## 5. Copiar os arquivos do bot

Pegue os arquivos da pasta `mql4/` deste projeto e copie para a Pasta de Dados:

1. Copie **`mql4/Experts/SmartTraderEA.mq4`** para **`MQL4\Experts\`**.
2. Copie **todos os `.mqh`** de **`mql4/Include/`**
   (`Indicators.mqh`, `RiskManager.mqh`, `AIBridge.mqh`) para
   **`MQL4\Include\`**.

> ⚠️ **Importante:** os 3 includes precisam estar em `MQL4\Include`, senão a
> compilação falha com erro de "arquivo não encontrado" (`cannot open include
> file`). Não deixe o EA "sozinho" sem os includes.

Depois de copiar, no MT4 abra a janela **Navegador** (*Navigator*, atalho
**Ctrl+N**), clique com o botão direito em **"Expert Advisors"** e escolha
**"Atualizar"** (*Refresh*). O `SmartTraderEA` deve aparecer na lista.

---

## 6. Compilar no MetaEditor (F7)

O arquivo `.mq4` é o **código-fonte**. O MT4 só executa a versão **compilada**
(`.ex4`). Compilar é traduzir o código para o robô rodar.

1. No Navegador, **clique duplo** em `SmartTraderEA` (ou botão direito >
   **"Modificar"** / *Modify*). Isso abre o **MetaEditor**.
2. No MetaEditor, pressione **F7** (ou botão **"Compilar"** / *Compile*).
3. Olhe a aba **"Erros"** (*Errors*) na parte de baixo:
   - **0 erros, 0 avisos** → sucesso! Gerou o `SmartTraderEA.ex4`.
   - **Avisos** (*warnings*) → geralmente não impedem de rodar, mas vale ler.
   - **Erros** (*errors*) → precisa corrigir antes de usar.

### Se aparecerem erros de compilação

| Erro comum | Causa provável | O que fazer |
|------------|----------------|-------------|
| `cannot open include file 'Indicators.mqh'` | Include faltando | Confirme que os 3 `.mqh` estão em `MQL4\Include`. |
| `'X' - undeclared identifier` | Variável/função não definida | Pode ser que o EA esteja em construção (Fase 1). Veja o status no `README.md`. |
| `'X' - function already defined` | Arquivo duplicado | Verifique se você não copiou o mesmo include em dois lugares. |
| `wrong parameters count` | Assinatura diferente do contrato | Confira `docs/ARQUITETURA.md` — funções devem bater com o contrato. |

> 💡 Após corrigir, é só apertar **F7** de novo. Toda vez que você edita o
> código, precisa recompilar.

---

## 7. Anexar o EA ao gráfico e ligar o AutoTrading

1. Abra um gráfico do símbolo que quer operar: na *Market Watch*, clique com o
   botão direito em **EURUSD** (recomendado para começar — par líquido e de
   spread baixo) > **"Janela do Gráfico"** (*Chart Window*).
2. Escolha o **timeframe** na barra de ferramentas (ex.: **M15** = 15 minutos).
3. No Navegador, **arraste** `SmartTraderEA` para cima do gráfico (ou clique
   duplo). Abre a janela de configuração (veja a seção 8).
4. Na aba **"Comum"** (*Common*), marque **"Permitir negociação automática"**
   (*Allow Automated Trading*) e, se for usar IA, **"Permitir importação de
   DLL"** não é necessário — usamos `WebRequest`, configurado na seção 10.
5. Clique em **OK**.

### O rostinho 😊 vs ✗

No canto **superior direito do gráfico**, ao lado do nome do EA, aparece um
ícone que diz se o robô está ativo:

| Ícone | Significado |
|-------|-------------|
| 😊 (rostinho sorrindo) | EA **ativo** e pronto para operar. |
| ☹ / ✗ (rosto triste ou X) | EA anexado, mas **não vai operar** — o AutoTrading está desligado. |

Se aparecer o rosto triste, clique no botão **"AutoTrading"** (*Auto Trading*)
na **barra de ferramentas do topo** do MT4. Ele fica:

- **Verde** = negociação automática **LIGADA** (global, para todos os EAs).
- **Vermelho** = **DESLIGADA**.

> ⚠️ São **dois interruptores**: o botão global "AutoTrading" da barra de
> ferramentas **E** a permissão "Permitir negociação automática" nas opções do
> EA. Os **dois** precisam estar ligados para o rostinho ficar 😊.

---

## 8. Configurar os inputs do EA

Quando você anexa o EA (ou clica com o botão direito no gráfico >
**"Lista de Especialistas"** > **"Propriedades"**, atalho **F7** no gráfico),
abre a aba **"Entradas"** (*Inputs*). Aqui estão os parâmetros principais e
recomendações **conservadoras para iniciante**:

| Input | O que faz | Sugestão p/ iniciante |
|-------|-----------|------------------------|
| `RiskPercent` | % do saldo arriscado por operação. Define o tamanho do lote. | **0.5 a 1.0** (nunca acima de 2%). |
| `StopLossPips` | Distância do stop loss, em pips. Limita a perda de cada trade. | **20 a 50** (depende do símbolo/timeframe). **Nunca 0.** |
| `TakeProfitPips` | Distância do alvo de lucro, em pips. | **40 a 100** (mire em ~2x o StopLoss). |
| `MagicNumber` | "Crachá" único das ordens deste EA. Permite ao bot reconhecer só as ordens dele. | Qualquer número único, ex.: **20240601**. Use um diferente por gráfico/EA. |
| `UseAI` | Liga (`true`) ou desliga (`false`) a camada de IA. | **`false`** para começar (só técnica). Ver seção 10. |
| `AIServerURL` | Endereço do serviço de IA. | `http://127.0.0.1:5000/signal` (só usado se `UseAI=true`). |

**Por que começar com `UseAI=false`?** O bot funciona **só com análise
técnica** quando a IA está desligada. A IA é **opcional** — uma camada extra.
Comece simples, valide a estratégia técnica, e só depois ligue a IA.

**Relação risco/retorno:** mantenha `TakeProfitPips` maior que `StopLossPips`
(ex.: SL 30 / TP 60 = razão 1:2). Assim você pode acertar menos da metade das
operações e ainda ficar no positivo.

---

## 9. Avisos de segurança (leia com atenção)

Estas regras vêm do contrato do projeto (`docs/ARQUITETURA.md`) e são
**inegociáveis**:

- ✅ **Sempre demo primeiro.** Conta real só muito depois, com a estratégia
  validada em backtest **e** em demo prolongada.
- ✅ **Nunca opere sem Stop Loss.** `StopLossPips` jamais deve ser 0. Uma
  operação sem stop pode zerar a conta num movimento forte.
- ✅ **Trava de perda diária.** O `RiskManager` desliga o bot no dia ao bater a
  perda máxima diária. Mantenha essa proteção ligada — ela evita que um dia
  ruim vire um desastre.
- ✅ **Risco baixo por trade.** 0,5%–1% por operação. Com 1%, seriam precisas
  muitas perdas seguidas para um rombo grande; com 10%, poucas já arrasam.
- ✅ **Comece com um símbolo só** (EURUSD) e **um gráfico**. Não espalhe o bot
  em 10 pares antes de entender como ele se comporta.
- ⚠️ **Nenhum bot garante lucro.** Ele te dá disciplina (segue regra, controla
  risco, opera sem emoção), mas o resultado depende da estratégia e do mercado.

---

## 10. Ligar a camada de IA (opcional)

A IA é **opcional**. Com `UseAI=false`, o bot opera só com técnica e você não
precisa de nada disto. Ligue a IA só quando quiser a camada extra.

### Passo A — Rodar o serviço de IA (Python)

O serviço fica em `ai/server.py` e roda **no seu próprio computador**,
respondendo em `http://127.0.0.1:5000`. Siga as instruções de
**`ai/README.md`** para instalar as dependências (`ai/requirements.txt`) e
iniciar o servidor. Em resumo, costuma ser algo como:

```bash
pip install -r ai/requirements.txt
python ai/server.py
```

Deixe esse terminal **aberto** enquanto o bot estiver rodando com a IA ligada.
Para um teste rápido de que está no ar, você pode abrir
`http://127.0.0.1:5000` no navegador (a resposta exata depende do servidor —
veja `ai/README.md`).

### Passo B — Liberar o WebRequest no MT4

Por segurança, o MT4 **bloqueia** chamadas de rede (`WebRequest`) por padrão.
Você precisa autorizar o endereço do serviço de IA:

1. Menu **Ferramentas** (*Tools*) > **Opções** (*Options*).
2. Aba **"Expert Advisors"** (*Expert Advisors*).
3. Marque **"Permitir WebRequest para as URLs listadas"**
   (*Allow WebRequest for listed URL*).
4. Na lista, **adicione**: `http://127.0.0.1:5000`
5. Clique em **OK**.

> ⚠️ Adicione exatamente `http://127.0.0.1:5000` (sem o `/signal` no final — o
> MT4 libera o **host**, não a rota específica). Se esquecer este passo, o
> `AIBridge` vai falhar nas chamadas e, conforme o contrato, `GetAISignal`
> retorna **0** (neutro) em erro/timeout — ou seja, o bot continua, só sem o
> palpite da IA.

### Passo C — Ligar no EA

1. Nas **Entradas** do EA, mude `UseAI` para **`true`**.
2. Confirme que `AIServerURL` está como `http://127.0.0.1:5000/signal`.
3. Clique em **OK** e confirme que o rostinho está 😊.

> 💡 **Backtest e IA:** o Strategy Tester do MT4 **bloqueia o WebRequest**, ou
> seja, a IA **não funciona** no backtest. Por isso, teste a **estratégia
> técnica pura** (`UseAI=false`) no Strategy Tester, e teste a **IA** rodando
> em **conta demo em tempo real**. Detalhes em [`docs/BACKTEST.md`](BACKTEST.md).

---

## Próximos passos

1. Compilou sem erros e o rostinho está 😊? Ótimo.
2. Antes de deixar rodando em demo por dias, faça um **backtest** para validar
   a estratégia técnica: veja [`docs/BACKTEST.md`](BACKTEST.md).
3. Acompanhe a aba **"Especialistas"** (*Experts*) e **"Diário"** (*Journal*)
   na parte de baixo do MT4 para ver os logs do bot.
