# Backtest do SmartTraderEA no Strategy Tester do MT4

Antes de deixar o bot rodando em conta demo por dias — e muito antes de pensar
em dinheiro real — você precisa **testar a estratégia no passado**. O MetaTrader 4
tem um simulador embutido chamado **Strategy Tester** (Testador de Estratégia)
que "roda o filme" do mercado histórico e mostra como o EA teria se saído.

Este guia é para iniciantes. Faça os passos na ordem.

> ⚠️ **Verdade importante:** um backtest bonito **não garante** lucro no futuro.
> O passado não se repete igual. O backtest serve para **eliminar estratégias
> ruins** e ganhar confiança numa estratégia razoável — não para "provar" que
> você vai ganhar dinheiro.

---

## Índice
1. [O que é o Strategy Tester](#1-o-que-é-o-strategy-tester)
2. [Abrir o Strategy Tester](#2-abrir-o-strategy-tester)
3. [Configurar o teste](#3-configurar-o-teste)
4. [Qualidade de modelagem e histórico](#4-qualidade-de-modelagem-e-histórico)
5. [A limitação da IA no backtest](#5-a-limitação-da-ia-no-backtest-importante)
6. [Rodar o teste e ler o relatório](#6-rodar-o-teste-e-ler-o-relatório)
7. [Números saudáveis vs sinais de alerta](#7-números-saudáveis-vs-sinais-de-alerta)
8. [Otimização de parâmetros](#8-otimização-de-parâmetros)
9. [Overfitting e validação fora da amostra](#9-overfitting-e-validação-fora-da-amostra)
10. [Checklist antes de ir para demo prolongada](#10-checklist-antes-de-ir-para-demo-prolongada)

---

## 1. O que é o Strategy Tester

É um **simulador**: ele pega dados históricos de preço (candles passados) e
faz o seu EA "reviver" aquele período tick a tick, abrindo e fechando ordens
como faria de verdade. No fim, gera um **relatório** com lucro, número de
operações, drawdown, etc.

Vantagem: você simula **anos de mercado em minutos**, com dinheiro de mentira e
sem esperar o tempo passar.

> 💡 Pré-requisito: o EA precisa estar **compilado sem erros** (gerou o
> `.ex4`). Se ainda não compilou, veja [`docs/INSTALACAO.md`](INSTALACAO.md),
> seção 6.

---

## 2. Abrir o Strategy Tester

No MT4, use **um** destes caminhos:

- Menu **Exibir** (*View*) > **Testador de Estratégia** (*Strategy Tester*), ou
- Atalho de teclado **Ctrl + R**, ou
- Clique no ícone de **Strategy Tester** na barra de ferramentas.

Abre um painel na parte de baixo da tela com várias caixas de configuração.

---

## 3. Configurar o teste

Preencha os campos do painel do testador:

| Campo | O que escolher | Observação |
|-------|----------------|------------|
| **Expert** (Especialista) | `SmartTraderEA` | Tem que aparecer compilado na lista. |
| **Símbolo** (Symbol) | `EURUSD` | Comece por um par líquido e de spread baixo. |
| **Período** (Period / timeframe) | `M15` (ou o mesmo que vai usar na demo) | Teste no **mesmo timeframe** que pretende operar. |
| **Modelo** (Model) | **"Todos os ticks"** (*Every tick*) | O mais **preciso** (e mais lento). Ver tabela abaixo. |
| **Spread** | "Atual" (*Current*) ou um valor fixo realista | Spread muito baixo = teste otimista demais. |
| **Use date** (Usar data) | Marque e defina **intervalo de datas** | Ex.: 2 a 5 anos de histórico. |
| **Visual mode** (Modo visual) | Opcional, marque para **ver** as operações no gráfico | Mais lento; bom para entender, ruim para otimizar. |

### Modelos de modelagem (o campo "Model")

| Modelo | Precisão | Velocidade | Quando usar |
|--------|----------|------------|-------------|
| **Todos os ticks** (*Every tick*) | Alta (a mais realista no MT4) | Lenta | **Sempre que possível** — é a recomendada. |
| **Pontos de controle** (*Control points*) | Média (aproxima ticks) | Média | Só para uma prévia rápida. |
| **Preços de abertura** (*Open prices only*) | Baixa | Muito rápida | Só para EAs que decidem **no fechamento do candle**; pode enganar. |

> ⚠️ O SmartTraderEA pode reagir dentro do candle (ex.: stop/take, trailing).
> Use **"Todos os ticks"** para um teste em que você possa confiar. "Preços de
> abertura" tende a mostrar resultados otimistas e irreais.

Depois de configurar, **antes de rodar**, clique em **"Propriedades do
Especialista"** (*Expert properties*) para ajustar os **inputs** do EA — os
mesmos da [`docs/INSTALACAO.md`](INSTALACAO.md), seção 8 (`RiskPercent`,
`StopLossPips`, `TakeProfitPips`, `MagicNumber`, `UseAI`, etc.). **Comece com
`UseAI=false`** (veja a seção 5 abaixo).

---

## 4. Qualidade de modelagem e histórico

No fim do relatório aparece a **Qualidade de Modelagem** (*Modelling Quality*),
em **porcentagem**. Ela diz o quão fiel foi a simulação dos ticks.

| Modelling Quality | Leitura |
|-------------------|---------|
| **~90%** | Excelente. É o teto prático do MT4 com bons dados. Confie mais. |
| **50% a 90%** | Aceitável, mas há buracos no histórico. Interprete com cautela. |
| **n/a ou baixo** | Histórico ruim/incompleto. **Não confie** no resultado. |

**Por que isso importa:** se o MT4 não tem dados de boa qualidade, ele
"inventa" o movimento dentro do candle por interpolação. Resultado: o teste
pode mostrar entradas/saídas que **não teriam acontecido** na realidade.

**Como melhorar a qualidade do histórico:**

1. Abra o **Centro de Histórico** (*History Center*) em **Ferramentas** (*Tools*)
   > **Centro de Histórico** (ou **F2**).
2. Selecione o símbolo e o timeframe e **baixe/atualize** os dados da corretora.
3. Quanto mais dados reais baixados, maior tende a ser a Modelling Quality.

> 💡 A maior qualidade vem dos dados de **M1** (1 minuto), pois o MT4 usa M1
> para reconstruir os ticks de timeframes maiores. Ter M1 farto melhora o teste
> de M15, H1, etc.

---

## 5. A limitação da IA no backtest (IMPORTANTE)

A camada de IA do projeto conversa com um serviço Python externo via
**`WebRequest`** (HTTP local — ver [`docs/ARQUITETURA.md`](ARQUITETURA.md)).

**O Strategy Tester do MT4 BLOQUEIA o `WebRequest`.** Ou seja: **dentro do
backtest a IA não funciona**. Se você rodar com `UseAI=true` no testador, as
chamadas falham e, conforme o contrato, `GetAISignal` retorna **0** (neutro) —
o resultado **não reflete** a IA de verdade.

**O que fazer:**

| Camada | Onde testar |
|--------|-------------|
| **Estratégia técnica** (`UseAI=false`) | **Strategy Tester** (este guia). Valide aqui. |
| **Camada de IA** (`UseAI=true`) | **Conta demo em tempo real** (servidor Python rodando, WebRequest liberado). |

Ou seja:

- No backtest, sempre **`UseAI=false`**. Você valida a base técnica.
- A IA você avalia **na conta demo ao vivo**, com o serviço `ai/server.py` no ar
  e a URL liberada em *Ferramentas > Opções > Expert Advisors*
  (passo a passo em [`docs/INSTALACAO.md`](INSTALACAO.md), seção 10).

---

## 6. Rodar o teste e ler o relatório

1. Clique em **"Iniciar"** (*Start*). A barra de progresso anda.
2. Ao terminar, veja as abas na parte de baixo:
   - **Resultados** (*Results*): lista de todas as operações.
   - **Gráfico** (*Graph*): a **curva de capital** (saldo ao longo do tempo).
   - **Relatório** (*Report*): o resumo com as métricas-chave.
   - **Diário** (*Journal*): mensagens e erros do EA durante o teste.

### A curva de capital (olhe primeiro)

No **Gráfico**, você quer uma linha que **sobe de forma relativamente suave**,
da esquerda para a direita. Sinais ruins: linha em escada com quedas enormes,
ou que sobe só no começo e depois desaba.

### As métricas-chave do Relatório

| Métrica | O que é | Por que importa |
|---------|---------|-----------------|
| **Lucro líquido** (*Total net profit*) | Ganhos − perdas, no fim do período. | O resultado final. Tem que ser **positivo**, mas sozinho não basta. |
| **Fator de lucro** (*Profit factor*) | Lucro bruto ÷ prejuízo bruto. | **> 1** dá lucro. Quanto maior, melhor (ver tabela na seção 7). |
| **Rebaixamento máximo** (*Maximal drawdown*) | Maior queda do pico ao fundo da conta (em % e $). | Mede o **pior momento**. Drawdown alto = sustos grandes e risco de quebrar. |
| **% de acerto** (*Profit trades %*) | % de operações vencedoras. | Importante, **mas** uma estratégia pode acertar pouco e lucrar (TP > SL). |
| **Total de operações** (*Total trades*) | Quantos trades no período. | Poucas operações = estatística frágil (ver seção 7). |
| **Expectância** (*Expected payoff*) | Lucro médio **por operação**. | Quanto você ganha, em média, cada vez que opera. Tem que ser **positivo**. |

> 💡 **Expectância** é o número mais honesto: positivo significa que, em média,
> cada operação adiciona dinheiro. Negativo significa que **operar mais te faz
> perder mais**, mesmo que o lucro total pareça ok por sorte.

---

## 7. Números saudáveis vs sinais de alerta

Não existem valores mágicos, mas estas faixas ajudam a calibrar a leitura:

| Métrica | Saudável | Sinal de alerta |
|---------|----------|-----------------|
| **Fator de lucro** | **1,3 a 2,0** | Acima de **3,0** com poucos trades → bom demais para ser verdade (overfitting). |
| **Drawdown máximo** | Abaixo de **~20%** | Acima de **30–40%** → você quebraria a conta no caminho. |
| **Total de operações** | **> 100** (idealmente 200+) | **< 30** → amostra pequena demais, pode ser sorte. |
| **% de acerto** | Coerente com a razão SL/TP | 90%+ de acerto com TP minúsculo e SL gigante → mascara risco. |
| **Expectância** | **Positiva** e estável | Negativa, ou positiva só por 1–2 trades enormes. |

### Os três grandes perigos

1. **Overfitting (sobreajuste):** o EA foi "moldado" para o passado exato e não
   generaliza. Suspeite quando os números são **espetaculares** e o teste tem
   **poucas operações** num período curto. Ver seção 9.
2. **Poucas operações:** 10 trades lucrativos podem ser pura sorte. Mais
   operações = conclusão mais confiável. Prefira períodos longos.
3. **Curva "perfeita":** uma linha de capital reta, sem nenhuma queda, quase
   sempre indica teste irreal (spread baixo demais, modelo "preços de abertura",
   ou parâmetros decorados).

---

## 8. Otimização de parâmetros

A aba/ caixa **"Otimização"** (*Optimization*) testa **várias combinações** de
inputs automaticamente e mostra quais deram os melhores resultados.

**Como usar:**

1. No painel do testador, marque a caixa **"Otimização"** (*Optimization*).
2. Em **"Propriedades do Especialista"** > aba **"Entradas"**, para cada input
   que quer variar, preencha:
   - **Start** (início), **Step** (passo) e **Stop** (fim), e marque a caixa do
     input.
   - Ex.: `StopLossPips` de **20** a **50**, passo **5**.
3. Na aba **"Otimização"** das propriedades, escolha o **critério** a maximizar
   (ex.: *Balance*, *Profit Factor*) e limites (ex.: drawdown máximo aceitável).
4. Clique em **"Iniciar"**. Ao fim, a aba **"Resultados da Otimização"**
   (*Optimization Results*) lista as combinações ordenadas.

> ⚠️ **Não varie muitos inputs de uma vez.** Cada input a mais multiplica o
> número de combinações (explosão combinatória) e **aumenta o risco de
> overfitting**. Otimize 1 a 3 parâmetros por vez, com passos largos.

---

## 9. Overfitting e validação fora da amostra

Este é **o** erro clássico de iniciante: você otimiza, acha a combinação
"perfeita" para 2020–2023, fica empolgado, vai pra demo... e o bot decepciona.
Motivo: você **decorou o passado**, não descobriu uma vantagem real.

### Como se proteger: validação fora da amostra (out-of-sample)

A ideia é **nunca** avaliar a estratégia nos mesmos dados em que ela foi
otimizada.

1. **Divida o histórico em duas partes:**
   - **In-sample** (amostra de treino): ex.: 2019–2022. Use **só** esta parte
     para **otimizar** os parâmetros.
   - **Out-of-sample** (amostra de validação): ex.: 2023–2024. Dados que a
     otimização **nunca viu**.
2. Pegue a melhor combinação encontrada no in-sample.
3. **Rode um teste único** dessa combinação no período out-of-sample.
4. **Compare:**
   - Se o desempenho out-of-sample for **parecido** com o in-sample → bom sinal,
     a estratégia generaliza.
   - Se **despencar** no out-of-sample → era overfitting. **Descarte** essa
     combinação.

### Walk-forward (validação mais robusta)

Versão avançada: você "anda" pela linha do tempo repetindo otimiza-num-bloco /
valida-no-bloco-seguinte, várias vezes. É mais trabalhoso, mas é o teste mais
honesto de que a estratégia se adapta ao longo do tempo. Comece pela divisão
simples in-sample / out-of-sample e evolua para walk-forward depois.

> 💡 **Regra de ouro:** se um resultado some quando você troca os dados, ele
> nunca foi real.

---

## 10. Checklist antes de ir para demo prolongada

Marque tudo antes de deixar o bot rodando dias seguidos em conta demo. E só
pense em **conta real muito depois**, com confirmação explícita (ver as regras
de segurança em [`docs/ARQUITETURA.md`](ARQUITETURA.md) e
[`docs/INSTALACAO.md`](INSTALACAO.md)).

- [ ] EA **compilado sem erros** (gerou o `.ex4`).
- [ ] Backtest feito com **"Todos os ticks"** e **Modelling Quality ~90%**.
- [ ] Histórico do símbolo **baixado/atualizado** (Centro de Histórico).
- [ ] Período de teste **longo** (anos) e com **muitas operações** (100+).
- [ ] Spread configurado de forma **realista** (não otimista demais).
- [ ] Testado com **`UseAI=false`** (a IA não roda no tester — seção 5).
- [ ] **Fator de lucro > 1,3**, **drawdown < ~20%**, **expectância positiva**.
- [ ] **Stop Loss sempre ativo** (`StopLossPips` nunca 0) e **risco baixo**
      por trade (0,5%–1%).
- [ ] Parâmetros validados **fora da amostra** (out-of-sample), não só no
      período otimizado (seção 9).
- [ ] Curva de capital **subindo de forma suave**, sem quedas catastróficas.

Passou em tudo? Então vá para a **conta demo em tempo real** — agora sim
podendo ligar a IA (`UseAI=true`) com o servidor Python no ar — e observe por um
bom tempo antes de qualquer próximo passo.

> ⚠️ **Lembrete final:** backtest e demo aprovados **não garantem** lucro real.
> O mercado muda. Mantenha as travas de risco ligadas, comece pequeno e nunca
> arrisque dinheiro que você não pode perder.
