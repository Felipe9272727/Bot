# 🤖📰 Motor de IA de Notícias (sinal de direção)

Serviço de IA que **lê notícias mundiais em tempo real**, interpreta o impacto
macro e devolve um **viés de direção** (comprar / vender / neutro) + confiança
para um ativo. Roda no dispositivo do usuário; o EA do MT4 consulta via HTTP.

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

## Arquitetura do serviço (no dispositivo do usuário)

```
[RSS/GDELT/Finnhub calendário]
        │  ingest (asyncio)
        ▼
[Dedup + filtro de relevância por símbolo]
        │
        ▼
[FinBERT — score barato p/ descartar ruído]   ← economiza chamadas de LLM
        │ (só notícia relevante passa)
        ▼
[LLM interpreta macro → viés direcional + confiança]
        │
        ▼
[Cache de viés por símbolo + TTL + modo defensivo]
        │  HTTP localhost
        ▼
[EA do MT4 consulta via WebRequest]
```

### Componentes
1. **Ingestor** — RSS (Reuters/Investing/FXStreet) a cada ~30-60s + GDELT DOC a
   cada 15 min + calendário econômico (Finnhub) 1×/h. Dedup por hash de título/URL.
2. **Pré-filtro barato** — relevância por palavra-chave/símbolo + FinBERT local
   para descartar notícia neutra **antes** de gastar uma chamada de LLM.
3. **Intérprete LLM** — só roda quando há notícia nova relevante. Prompt pede
   cadeia causal + forças conflitantes + viés + confiança, com instrução explícita
   de devolver NEUTRO em ambiguidade.
4. **Cache/estado** — viés por símbolo com **TTL** (ex.: 2-6h) e decaimento de
   confiança no tempo.
5. **Modo defensivo** — nos ±15 min de evento de alto impacto (NFP, FOMC, CPI),
   retorna `blocked=true` (não tenta adivinhar o spike).
6. **Servidor HTTP** (Flask/FastAPI) em `127.0.0.1`.

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

## Contrato HTTP (EA ↔ serviço)

**Requisição** (EA → serviço):
```
GET /bias?symbol=USDCAD
```

**Resposta** (serviço → EA):
```json
{
  "symbol": "USDCAD",
  "bias": "sell",            // buy | sell | neutral
  "confidence": 0.62,         // 0..1
  "horizon_hours": 4,
  "rationale": "Alta do petroleo favorece CAD; safe-haven USD compensa em parte",
  "as_of": "2026-06-02T13:40:00Z",
  "ttl_seconds": 1800,
  "blocked": false,           // true em janela de evento de alto impacto
  "stale": false
}
```

## Fail-safe (essencial)

Se o LLM/API falhar, o TTL expirar, ou houver evento de alto impacto iminente →
retornar `bias:"neutral"` com `blocked`/`stale` apropriados. **A regra no EA:**

- A técnica **só executa se o viés confirmar** (Modo A) ou **se o viés não vetar**
  (Modo B) — ver `ESTRATEGIA.md`.
- Viés `neutral` / `stale` / `blocked`: a IA **nunca força entrada**; no máximo a
  técnica opera sozinha (Modo B) ou não opera (Modo A).
- `WebRequest` com timeout curto e fallback para neutro.

## Plano de adoção (sem ilusão)

1. **Modo log-only primeiro:** o serviço gera viés e **só registra**, sem bloquear
   nada. Mede-se se o viés teria melhorado o expectancy da estratégia técnica.
2. Só depois de comprovar valor, deixa-se a IA **vetar/dimensionar** de verdade.
3. **Nunca** operar no spike do evento de alto impacto.

> Custo de LLM controlado: ele só roda em **notícia nova relevante** (não a cada
> consulta do EA), então cabe em tier grátis/baixo.
