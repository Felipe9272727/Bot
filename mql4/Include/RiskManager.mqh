//+------------------------------------------------------------------+
//|                                                 RiskManager.mqh   |
//|        Gestao de risco e dimensionamento de posicao               |
//|        Contrato: docs/ARQUITETURA.md                              |
//+------------------------------------------------------------------+
#property strict

//--- Parametros configuraveis de risco (inputs do EA).
//    Declarados como 'extern' para que aparecam na janela de inputs
//    do Expert Advisor que inclui este arquivo. Como o EA inclui o
//    .mqh (em vez de redeclarar as variaveis), nao ha conflito de
//    "variable already defined".
extern int    MaxOpenTrades       = 1;     // Numero maximo de posicoes simultaneas (deste magic)
extern double MaxDailyLossPercent = 5.0;   // Perda diaria maxima (% do saldo) que bloqueia novas entradas

//+------------------------------------------------------------------+
//| RM_PipPoint                                                       |
//| Retorna o tamanho de 1 "pip" em termos de preco para o simbolo.   |
//| Trata corretoras de 5 e 3 digitos: nesses casos 1 pip = 10 points,|
//| pois o ultimo digito e fracionario (point != pip).                |
//|                                                                   |
//| OBS: o nome leva o prefixo 'RM_' para NAO colidir com a funcao    |
//| PipPoint() ja definida no Expert (SmartTraderEA.mq4), evitando o  |
//| erro de compilacao "function already defined" quando o EA inclui  |
//| este arquivo. A logica e identica a do EA.                        |
//+------------------------------------------------------------------+
double RM_PipPoint(string symbol)
{
   double point  = MarketInfo(symbol, MODE_POINT);
   int    digits = (int)MarketInfo(symbol, MODE_DIGITS);

   //--- 3 ou 5 digitos => cotacao fracionaria => 1 pip = 10 points
   if(digits == 3 || digits == 5)
      return(point * 10.0);

   //--- 2 ou 4 digitos => 1 pip = 1 point
   return(point);
}

//+------------------------------------------------------------------+
//| NormalizeLot                                                      |
//| Ajusta o lote aos limites do simbolo:                             |
//|  - MODE_MINLOT  : lote minimo permitido                           |
//|  - MODE_MAXLOT  : lote maximo permitido                           |
//|  - MODE_LOTSTEP : incremento minimo (passo)                       |
//| O lote e arredondado ao passo mais proximo e depois "clampado"    |
//| entre min e max. A casa decimal final segue o numero de casas do  |
//| proprio lotstep.                                                  |
//+------------------------------------------------------------------+
double NormalizeLot(string symbol, double lot)
{
   double minLot  = MarketInfo(symbol, MODE_MINLOT);
   double maxLot  = MarketInfo(symbol, MODE_MAXLOT);
   double lotStep = MarketInfo(symbol, MODE_LOTSTEP);

   //--- Protecao contra valores invalidos retornados pela corretora
   if(lotStep <= 0.0) lotStep = 0.01;
   if(minLot  <= 0.0) minLot  = lotStep;

   //--- Arredonda ao passo mais proximo
   lot = MathRound(lot / lotStep) * lotStep;

   //--- Numero de casas decimais do passo (ex.: 0.01 -> 2 casas)
   int lotDigits = 0;
   double step = lotStep;
   while(step < 1.0 && lotDigits < 8)
   {
      step *= 10.0;
      lotDigits++;
   }
   lot = NormalizeDouble(lot, lotDigits);

   //--- Garante que fique dentro dos limites do simbolo
   if(lot < minLot) lot = minLot;
   if(maxLot > 0.0 && lot > maxLot) lot = maxLot;

   return(lot);
}

//+------------------------------------------------------------------+
//| CalculateLotSize                                                  |
//| Calcula o lote para arriscar 'riskPercent'% do AccountBalance()   |
//| dado o stop loss em pips.                                         |
//|                                                                   |
//| Logica:                                                           |
//|   risco$ = saldo * (riskPercent/100)                              |
//|   valor de 1 pip por lote = TICKVALUE * (pip / TICKSIZE)          |
//|   perda por lote no stop  = stopLossPips * valorPipPorLote        |
//|   lote = risco$ / perda por lote                                  |
//|                                                                   |
//| MODE_TICKVALUE = valor monetario de 1 tick para 1.0 lote.         |
//| MODE_TICKSIZE  = tamanho minimo de variacao de preco (1 tick).    |
//| Convertemos pips -> ticks usando PipPoint/tickSize.               |
//+------------------------------------------------------------------+
double CalculateLotSize(string symbol, double riskPercent, double stopLossPips)
{
   //--- Entradas invalidas => devolve o lote minimo normalizado (fail-safe)
   if(riskPercent <= 0.0 || stopLossPips <= 0.0)
   {
      Print("CalculateLotSize: parametros invalidos (riskPercent=", riskPercent,
            ", stopLossPips=", stopLossPips, ") -> usando lote minimo.");
      return(NormalizeLot(symbol, 0.0));
   }

   double balance   = AccountBalance();
   double riskMoney = balance * (riskPercent / 100.0);

   double tickValue = MarketInfo(symbol, MODE_TICKVALUE); // $ por tick / lote
   double tickSize  = MarketInfo(symbol, MODE_TICKSIZE);  // preco por tick
   double pip       = RM_PipPoint(symbol);                // preco por pip

   //--- Alguns simbolos/configuracoes nao expoem TICKSIZE; cai para MODE_POINT
   if(tickSize <= 0.0)
      tickSize = MarketInfo(symbol, MODE_POINT);

   //--- Protecao contra divisao por zero ou dados ausentes
   if(tickValue <= 0.0 || tickSize <= 0.0 || pip <= 0.0)
   {
      Print("CalculateLotSize: MarketInfo invalido para ", symbol,
            " (tickValue=", tickValue, ", tickSize=", tickSize, ", pip=", pip,
            ") -> usando lote minimo.");
      return(NormalizeLot(symbol, 0.0));
   }

   //--- Valor monetario de 1 pip para 1.0 lote
   double pipValuePerLot = tickValue * (pip / tickSize);

   //--- Perda monetaria por lote caso o stop seja atingido
   double lossPerLot = stopLossPips * pipValuePerLot;

   if(lossPerLot <= 0.0)
   {
      Print("CalculateLotSize: perda por lote invalida para ", symbol,
            " -> usando lote minimo.");
      return(NormalizeLot(symbol, 0.0));
   }

   //--- Lote bruto antes de normalizar
   double lot = riskMoney / lossPerLot;

   //--- Ajusta aos limites do simbolo (min/max/step)
   return(NormalizeLot(symbol, lot));
}

//+------------------------------------------------------------------+
//| CountOpenTrades                                                  |
//| Conta as posicoes (mercado) atualmente abertas com o magic dado. |
//| Considera apenas OP_BUY e OP_SELL (ignora ordens pendentes).     |
//+------------------------------------------------------------------+
int CountOpenTrades(int magic)
{
   int count = 0;
   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderMagicNumber() != magic)
         continue;
      if(OrderType() == OP_BUY || OrderType() == OP_SELL)
         count++;
   }
   return(count);
}

//+------------------------------------------------------------------+
//| DailyProfit                                                      |
//| Calcula o resultado do dia (em moeda da conta):                  |
//|  - Soma lucro + swap + comissao das ordens FECHADAS hoje         |
//|    (filtradas por OrderCloseTime() >= inicio do dia).            |
//|  - Soma o lucro FLUTUANTE das posicoes atualmente abertas.       |
//| Retorna valor positivo (ganho) ou negativo (prejuizo).          |
//+------------------------------------------------------------------+
double DailyProfit(int magic)
{
   //--- Inicio do dia corrente (00:00 da data atual do servidor)
   datetime dayStart = StrToTime(TimeToStr(TimeCurrent(), TIME_DATE));
   double   total    = 0.0;

   //--- 1) Ordens fechadas hoje (historico)
   int hist = OrdersHistoryTotal();
   for(int i = 0; i < hist; i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
         continue;
      if(OrderMagicNumber() != magic)
         continue;
      //--- Apenas trades de mercado fechados (ignora pendentes canceladas)
      if(OrderType() != OP_BUY && OrderType() != OP_SELL)
         continue;
      if(OrderCloseTime() < dayStart)
         continue;

      total += OrderProfit() + OrderSwap() + OrderCommission();
   }

   //--- 2) Lucro flutuante das posicoes abertas (independe da data de abertura)
   int open = OrdersTotal();
   for(int j = 0; j < open; j++)
   {
      if(!OrderSelect(j, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderMagicNumber() != magic)
         continue;
      if(OrderType() != OP_BUY && OrderType() != OP_SELL)
         continue;

      total += OrderProfit() + OrderSwap() + OrderCommission();
   }

   return(total);
}

//+------------------------------------------------------------------+
//| CanOpenTrade                                                     |
//| Travas globais de seguranca antes de permitir nova entrada:      |
//|  1) Numero maximo de posicoes simultaneas (MaxOpenTrades).       |
//|  2) Perda diaria maxima (MaxDailyLossPercent): se o prejuizo do  |
//|     dia (fechado hoje + flutuante atual) exceder o limite, bloqueia|
//|     novas entradas no resto do dia.                              |
//| Retorna true se for seguro abrir; false caso contrario.          |
//+------------------------------------------------------------------+
bool CanOpenTrade(int magic)
{
   //--- 1) Limite de posicoes simultaneas
   int openTrades = CountOpenTrades(magic);
   if(openTrades >= MaxOpenTrades)
   {
      Print("CanOpenTrade: bloqueado - limite de posicoes atingido (",
            openTrades, "/", MaxOpenTrades, ").");
      return(false);
   }

   //--- 2) Trava de perda diaria maxima
   if(MaxDailyLossPercent > 0.0)
   {
      double dayResult   = DailyProfit(magic);            // negativo = prejuizo
      double balance     = AccountBalance();
      double lossLimit   = balance * (MaxDailyLossPercent / 100.0); // valor positivo

      //--- dayResult negativo cujo modulo excede o limite => bloqueia
      if(dayResult <= -lossLimit)
      {
         Print("CanOpenTrade: bloqueado - perda diaria maxima atingida. ",
               "Resultado do dia=", DoubleToStr(dayResult, 2),
               " | Limite=", DoubleToStr(-lossLimit, 2),
               " (", DoubleToStr(MaxDailyLossPercent, 2), "% do saldo).");
         return(false);
      }
   }

   //--- Nenhuma trava acionada: pode operar
   return(true);
}
//+------------------------------------------------------------------+
