# 🤖📰 Motor de IA de Notícias (sinal de direção)

Motor de IA que **lê notícias mundiais em tempo real**, interpreta o impacto
macro e devolve um **viés de direção** (comprar / vender / neutro) + confiança
para um ativo. É um **módulo Python** (`smarttrader/news_ai.py`) chamado **em
processo** pelo trader — **não** há servidor HTTP nem ponte entre processos. O
mesmo processo Python que comanda o MetaTrader 5 importa o motor e o consulta
diretamente (ver `docs/ARQUITETURA.md`).

> ⚠️ **Expectativa realista (honestidade obrigatória):** notícia "óbvia" já entra
> no preço em segundos por algoritmos institucionais. A borda de varejo **não está
> em reagir à manchete**, e sim em capturar **mudança de narrativa macro** que dura
> horas/dias (swing). Estudos mostram que o "alfa" de IA-de-notícias **vem caindo**
> conforme mais gente usa (Sharpe de estratégias GPT-4 caiu de ~6,5 em 2021 para
> ~1,2 em 2024). Por isso tratamos a IA como **veto/viés de qualidade**, não bola
> de cristal.

Fontes: [News-driven FX (FXEmpire)](https://www.fxempire.com/education/article/news-driven-fx-trading-how-to-trade-events-like-the-fomc-cpi-and-nfp-1549791) ·
[Sentiment trading com LLMs (arXiv)](https://arxiv.org/pdf/2412.19245) ·
[Look-ahead bias GPT (arXiv)](https://arxiv.org/pdf/2309.17322) ·
[FinBERT (arXiv)](https://arxiv.org/abs/2306.02136)

## Como "crise no petróleo" vira direção

O LLM precisa raciocinar sobre **forças conflitantes**, não reagir a uma palavra:
- Petróleo sobe → CAD tende a fortalecer → **USDCAD cai**
- Mas crise geopolítica também liga *safe-haven* no USD (empurra USDCAD pra cima)
  e **ouro pra cima**
- Resultado = qual força domina. Se elas se cancelam → **NEUTRO** com confiança baixa.

Lição de design: o modelo deve poder dizer "não sei" (neutro), em vez de inventar
convicção. Fonte: [Petróleo x USDCAD](https://fortuneprime.com/education/geopolitical-oil-shocks-usd-cad-dynamics-explained/).

## Arquitetura do motor (módulo Python, em processo)

```
[RSS/GDELT/Finnhub calendário]   ← smarttrader/news_sources.py (ingestão)
        │  ingest
        ▼
[Dedup + filtro de relevância por símbolo]   ← news_sources.dedup() / filter_relevant()
        │
        ▼
[FinBERT — score barato p/ descartar ruído]   ← economiza chamadas de LLM
        │ (só notícia relevante passa)
        ▼
[LLM interpreta macro → viés direcional + confiança]
        │  (baseline auditável: smarttrader/news_mapper.py)
        ▼
[Cache de viés por símbolo + TTL + modo defensivo]
        │  chamada de função, NO MESMO processo
        ▼
[trader.py chama NewsBiasEngine.get_bias(symbol) -> Bias]
```

### Componentes
1. **Ingestor** (`smarttrader/news_sources.py`, já existe) — RSS
   (Reuters/Investing/FXStreet) a cada ~30-60s + GDELT DOC a cada 15 min +
   calendário econômico (Finnhub) 1×/h. Dedup por hash de título/URL e filtro de
   relevância por símbolo. Será plugado pelo gancho `_fetch_news`.
2. **Pré-filtro barato** — relevância por palavra-chave/símbolo + FinBERT local
   para descartar notícia neutra **antes** de gastar uma chamada de LLM. Plugado
   pelo gancho `_score_sentiment`.
3. **Intérprete macro** — `smarttrader/news_mapper.py` (já existe) é o **baseline
   determinístico e auditável** (macro→direção por regras), e o **LLM** entra como
   camada de interpretação mais rica. Só roda quando há notícia nova relevante.
   Pede cadeia causal + forças conflitantes + viés + confiança, com instrução
   explícita de devolver NEUTRO em ambiguidade. Plugado pelo gancho
   `_interpret_macro`.
4. **Cache/estado** — viés por símbolo com **TTL** (ex.: 2-6h) e decaimento de
   confiança no tempo (campo `_cache` em `NewsBiasEngine`).
5. **Modo defensivo** — nos ±15 min de evento de alto impacto (NFP, FOMC, CPI),
   retorna `blocked=True` (não tenta adivinhar o spike).

> Os ganchos `_fetch_news` / `_score_sentiment` / `_interpret_macro` já existem
> em `news_ai.py` como pontos de extensão (`NotImplementedError` por enquanto):
> são exatamente onde as peças acima se plugam, sem mudar o contrato público.

### Fontes de dados (todas com tier grátis)

| Fonte | Grátis | Uso |
|---|---|---|
| [GDELT 2.0 DOC API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) | Total | Cobertura global, temas/tom, risco geopolítico |
| RSS Reuters/Investing/FXStreet | Total | Baixa latência, zero custo |
| [Finnhub](https://finnhub.io/docs/api/company-news) | 60 req/min | Notícia + sentimento + **calendário** |
| [Alpha Vantage News](https://www.alphavantage.co/) | Limitado | Sentimento já pontuado por ticker |

### Sentimento / interpretação
- **FinBERT** (treinado em finanças, ~0,88 acc) como pré-filtro barato de sentimento.
- **LLM** para a interpretação macro→ativo (a parte que justifica a sua ideia).
- Léxicos (VADER, Loughran-McDonald) só como baseline — VADER não vai bem em finanças.

## Contrato (chamada em processo — `trader.py` → `news_ai.py`)

O trader importa o motor e chama um único método, no mesmo processo Python (sem
HTTP, sem serialização JSON, sem ponte):

```python
from smarttrader.news_ai import NewsBiasEngine, Bias

engine = NewsBiasEngine(news_api_key=..., llm_api_key=..., high_impact_calendar=...)
vies: Bias = engine.get_bias("USDCAD")
```

**Tipo de retorno** (`@dataclass Bias`, definido em `news_ai.py`):

```python
@dataclass
class Bias:
    symbol: str          # ativo, ex.: "USDCAD"
    bias: int            # 1 = comprar, -1 = vender, 0 = neutro/não operar
    confidence: float    # 0..1
    blocked: bool = False  # janela de evento de alto impacto (não operar o spike)
    stale: bool = False    # viés velho (TTL expirado) ou falha interna (fail-safe)
    rationale: str = ""    # explicação curta (cadeia causal)
```

Exemplo de viés para o caso "crise no petróleo":
`Bias(symbol="USDCAD", bias=-1, confidence=0.62, blocked=False, stale=False,
rationale="Alta do petroleo favorece CAD; safe-haven USD compensa em parte")`.

## Fail-safe (essencial)

Se o LLM/API falhar, o TTL expirar, ou houver evento de alto impacto iminente →
retornar um `Bias` NEUTRO (`bias=0`, `confidence=0`) com `blocked`/`stale`
apropriados. **A regra no trader:**

- A técnica **só executa se o viés confirmar** (Modo A) ou **se o viés não vetar**
  (Modo B) — ver `ESTRATEGIA.md`.
- Viés neutro / `stale` / `blocked`: a IA **nunca força entrada**; no máximo a
  técnica opera sozinha (Modo B) ou não opera (Modo A).
- **Qualquer exceção interna** em `get_bias` é capturada e vira NEUTRO com
  `stale=True`: a IA **nunca derruba o trader**. Como é chamada em processo, não
  há timeout de rede a gerenciar — o fail-safe é o `try/except` do próprio método.

## Plano de adoção (sem ilusão)

1. **Modo log-only primeiro:** o serviço gera viés e **só registra**, sem bloquear
   nada. Mede-se se o viés teria melhorado o expectancy da estratégia técnica.
2. Só depois de comprovar valor, deixa-se a IA **vetar/dimensionar** de verdade.
3. **Nunca** operar no spike do evento de alto impacto.

> Custo de LLM controlado: ele só roda em **notícia nova relevante** (não a cada
> chamada de `get_bias` do trader — o cache por símbolo com TTL evita isso),
> então cabe em tier grátis/baixo.
