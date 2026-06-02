# 🖥️ Rodar o bot 24h num VPS Windows (com MT5 demo/real)

Guia para quando você quiser o bot **operando sozinho 24 horas** (sem deixar seu
PC ligado e sem depender do Colab, que desconecta). Um **VPS** é um computador
Windows na nuvem, ligado o tempo todo, que você acessa remotamente.

> Comece sempre em **conta DEMO** + `DRY_RUN=true`. Só pense em real depois de
> semanas de demo com resultado consistente.

---

## 1. Conseguir um VPS Windows

Opções (do mais barato/simples ao mais "pronto"):

| Opção | Custo | Observação |
|---|---|---|
| **VPS do próprio broker** | Muitas vezes **grátis** | Vários brokers (ex.: os que usam MT5) dão VPS grátis se você tiver saldo/volume mínimo. Pergunte ao suporte do seu broker. |
| **Virtual Hosting do MetaTrader** | ~US$ 10-15/mês | Dá pra contratar de dentro do MT5 (menu *Registrar um VPS*). Bom p/ hospedar o terminal, mas o nosso bot é Python — confirme que permite instalar Python (alguns só rodam EA/sinais). |
| **VPS Windows genérico** | ~US$ 5-15/mês | Provedores de nuvem com Windows. É o mais flexível p/ instalar MT5 **+ Python + nosso bot**. |

Requisitos mínimos: **Windows**, 2 GB de RAM (4 GB folgado), e acesso via **Área
de Trabalho Remota (RDP)**.

---

## 2. Conectar no VPS
- No Windows: app **Conexão de Área de Trabalho Remota** (Remote Desktop).
- No celular/Mac: app **Microsoft Remote Desktop** (grátis).
- Use o **IP, usuário e senha** que o provedor te der.

---

## 3. Instalar tudo no VPS (uma vez)
Dentro do VPS (é um Windows normal):

1. **MetaTrader 5** — baixe em https://www.metatrader5.com/ → abra **conta demo** →
   anote login/senha/servidor. Em *Ferramentas → Opções → Expert Advisors*,
   marque **Permitir trading algorítmico**.
2. **Python 3.11+** — https://www.python.org/downloads/ (marque "Add to PATH").
3. **O projeto** — baixe/clone o repositório numa pasta.
4. No terminal (PowerShell), dentro da pasta do projeto:
   ```powershell
   pip install -r requirements.txt
   ```
   (No Windows isso instala também o pacote `MetaTrader5`.)
5. **Seu modelo de IA** — baixe a pasta `finbert_ft` (do seu Google Drive) pra
   dentro do projeto, se for usar a IA.
6. **Configuração** — copie `.env.example` para `.env` e preencha:
   - `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` (da conta **demo**)
   - `DRY_RUN=true` (começa só mostrando as decisões)
   - `USE_AI=false` (liga depois, quando quiser)

---

## 4. Rodar
Deixe o **terminal MT5 aberto e logado** no VPS, e rode:
```powershell
python -m smarttrader.trader --once     # 1 ciclo, em DRY_RUN: mostra a decisão
```
Quando confiar, mude `DRY_RUN=false` no `.env` (ainda na **conta demo**!) e rode
o laço 24h:
```powershell
python -m smarttrader.trader
```
- O bot fica rodando mesmo se você **desconectar** o RDP (o VPS continua ligado).
- Pare com **Ctrl+C** na janela do terminal.

> 💡 Dica: dá pra rodar o **paper trade** também no VPS
> (`python -m smarttrader.paper_trade`) antes de ligar no MT5 — mesmo bot, sem risco.

---

## 5. Checklist antes de qualquer dinheiro real
- [ ] Semanas em **demo** com o sistema completo (estratégia + IA + risco)
- [ ] Resultado e drawdown dentro do esperado (compare com o backtest)
- [ ] Você entende cada trava de risco do `risk.py`
- [ ] Só então, e com valor pequeno, considerar conta real

---

**Quando chegar a hora, me chama** que eu te acompanho passo a passo na escolha do
VPS e na configuração. 👍
