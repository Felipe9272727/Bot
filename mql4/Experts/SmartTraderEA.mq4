//+------------------------------------------------------------------+
//|                                              SmartTraderEA.mq4    |
//|                  Expert Advisor principal (Fase 1)               |
//|        Estrategia: cruzamento de EMA + filtro RSI (+ IA opcional) |
//|        Contrato de interface: docs/ARQUITETURA.md                |
//+------------------------------------------------------------------+
#property copyright "SmartTrader"
#property link      ""
#property version   "1.00"
#property strict

//--- Modulos do projeto (cada um segue o contrato em ARQUITETURA.md)
#include <Indicators.mqh>    // GetTechnicalSignal / GetRSI / GetEMA
                             //   + externs EMA_Fast, EMA_Slow, RSI_Period
#include <RiskManager.mqh>   // CalculateLotSize / CanOpenTrade / NormalizeLot
#include <AIBridge.mqh>      // GetAISignal  + externs UseAI, AIServerURL

//+------------------------------------------------------------------+
//| Inputs do EA                                                      |
//|                                                                   |
//| OBS: EMA_Fast, EMA_Slow, RSI_Period sao declarados como 'extern'  |
//| em Indicators.mqh, e UseAI/AIServerURL em AIBridge.mqh. Por isso  |
//| NAO sao re-declarados aqui (evita "variable already defined").    |
//| Eles continuam aparecendo na janela de inputs do EA.              |
//+------------------------------------------------------------------+
extern int    MagicNumber      = 20240601; // Identificador unico das ordens deste EA
extern double RiskPercent      = 1.0;      // % do saldo arriscado por trade
extern double StopLossPips     = 30.0;     // Stop Loss em pips
extern double TakeProfitPips   = 60.0;     // Take Profit em pips
extern double AIMinConfidence  = 0.60;     // Confianca minima exigida da IA (0..1)
extern double MaxSpreadPips    = 3.0;      // Spread maximo permitido (pips) para operar
extern int    Slippage         = 3;        // Desvio maximo de preco (pips) no OrderSend
extern bool   UseTrailing      = false;    // Ativa trailing stop
extern double TrailingStopPips = 20.0;     // Distancia do trailing stop em pips

//--- Estado interno
datetime g_lastBarTime = 0;  // Time[0] do ultimo candle processado

//+------------------------------------------------------------------+
//| PipPoint                                                          |
//| Retorna o valor de 1 "pip" em preco para o simbolo atual.         |
//| Em corretoras de 5/3 digitos, 1 pip = 10 * Point.                 |
//+------------------------------------------------------------------+
double PipPoint(string symbol)
{
   int digits = (int)MarketInfo(symbol, MODE_DIGITS);
   double point = MarketInfo(symbol, MODE_POINT);
   if(digits == 5 || digits == 3)
      return(point * 10.0);
   return(point);
}

//+------------------------------------------------------------------+
//| SpreadInPips                                                      |
//| Spread atual do simbolo convertido para pips.                     |
//+------------------------------------------------------------------+
double SpreadInPips(string symbol)
{
   double spreadPoints = MarketInfo(symbol, MODE_SPREAD); // spread em points
   double point = MarketInfo(symbol, MODE_POINT);
   double pip   = PipPoint(symbol);
   if(pip <= 0.0)
      return(0.0);
   // spreadPoints esta em 'points'; converte para preco e depois para pips
   return((spreadPoints * point) / pip);
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   //--- Validacoes basicas de configuracao
   if(StopLossPips <= 0.0)
   {
      Print("ERRO: StopLossPips deve ser > 0. EA sempre opera com stop (regra de seguranca).");
      return(INIT_PARAMETERS_INCORRECT);
   }
   if(RiskPercent <= 0.0)
   {
      Print("ERRO: RiskPercent deve ser > 0.");
      return(INIT_PARAMETERS_INCORRECT);
   }
   if(EMA_Fast >= EMA_Slow)
      Print("AVISO: EMA_Fast (", EMA_Fast, ") >= EMA_Slow (", EMA_Slow,
            "). Verifique os periodos.");

   g_lastBarTime = 0;

   Print("SmartTraderEA iniciado. Magic=", MagicNumber,
         " Risk=", DoubleToString(RiskPercent, 2), "%",
         " SL=", DoubleToString(StopLossPips, 1), "pips",
         " TP=", DoubleToString(TakeProfitPips, 1), "pips",
         " UseAI=", (UseAI ? "true" : "false"));

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("SmartTraderEA finalizado. Motivo=", reason);
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//| Laco principal de decisao. Opera apenas uma vez por candle novo.  |
//+------------------------------------------------------------------+
void OnTick()
{
   //--- 1) Trailing stop e gerenciado a cada tick (se ativado),
   //       independente de candle novo, para acompanhar o preco.
   if(UseTrailing)
      ManageTrailingStop();

   //--- 2) Detecta barra nova: so processa logica de entrada uma vez por candle.
   if(Time[0] == g_lastBarTime)
      return;
   g_lastBarTime = Time[0];

   //--- 3) Filtro de spread: nao operar com spread acima do limite.
   double spreadPips = SpreadInPips(Symbol());
   if(spreadPips > MaxSpreadPips)
   {
      Print("Spread alto (", DoubleToString(spreadPips, 1),
            " pips > ", DoubleToString(MaxSpreadPips, 1), "). Ignorando candle.");
      return;
   }

   //--- 4) Ja existe posicao aberta deste EA neste simbolo? Nao duplicar.
   if(HasOpenPosition(Symbol(), MagicNumber))
      return;

   //--- 5) Trava global de risco (perda diaria, nº max de posicoes, etc.).
   if(!CanOpenTrade(MagicNumber))
   {
      // RiskManager bloqueou a abertura (ex.: perda diaria maxima atingida).
      return;
   }

   //--- 6) Sinal tecnico (cruzamento de EMA + filtro RSI).
   int techSignal = GetTechnicalSignal(Symbol(), Period());
   if(techSignal == 0)
      return; // sem sinal -> nada a fazer

   //--- 7) Combina com a IA, se habilitada. So opera se AMBOS concordarem.
   int finalSignal = techSignal;
   if(UseAI)
   {
      int aiSignal = GetAISignal(Symbol(), Period());
      if(aiSignal != techSignal)
      {
         Print("Sinal tecnico (", techSignal, ") e IA (", aiSignal,
               ") divergem. Operacao cancelada.");
         return;
      }
      //--- Exige confianca minima da IA (g_LastAIConfidence vem do AIBridge,
      //    atualizado pela ultima chamada a GetAISignal).
      if(g_LastAIConfidence < AIMinConfidence)
      {
         Print("Confianca da IA (", DoubleToString(g_LastAIConfidence, 2),
               ") abaixo do minimo (", DoubleToString(AIMinConfidence, 2),
               "). Operacao cancelada.");
         return;
      }
      finalSignal = aiSignal;
   }

   //--- 8) Calcula lote pelo gerenciamento de risco e normaliza.
   double lot = CalculateLotSize(Symbol(), RiskPercent, StopLossPips);
   lot = NormalizeLot(Symbol(), lot);
   if(lot <= 0.0)
   {
      Print("Lote calculado invalido (", DoubleToString(lot, 2),
            "). Operacao cancelada.");
      return;
   }

   //--- 9) Executa a ordem (sempre com SL e TP).
   if(finalSignal == 1)
      OpenTrade(OP_BUY, lot);
   else if(finalSignal == -1)
      OpenTrade(OP_SELL, lot);
}

//+------------------------------------------------------------------+
//| OpenTrade                                                         |
//| Abre uma ordem de mercado SEMPRE com Stop Loss e Take Profit.     |
//| (Regra de seguranca: nunca abrir ordem sem stop.)                 |
//+------------------------------------------------------------------+
void OpenTrade(int orderType, double lot)
{
   string symbol = Symbol();
   double pip    = PipPoint(symbol);
   int    digits = (int)MarketInfo(symbol, MODE_DIGITS);

   double price = 0.0, sl = 0.0, tp = 0.0;
   color  arrow = clrNONE;

   //--- Distancia minima exigida pela corretora (em preco)
   double stopLevel = MarketInfo(symbol, MODE_STOPLEVEL) * MarketInfo(symbol, MODE_POINT);

   double slDist = StopLossPips   * pip;
   double tpDist = TakeProfitPips * pip;

   //--- Garante que SL/TP respeitem o STOPLEVEL minimo da corretora
   if(slDist < stopLevel) slDist = stopLevel;
   if(TakeProfitPips > 0.0 && tpDist < stopLevel) tpDist = stopLevel;

   if(orderType == OP_BUY)
   {
      price = NormalizeDouble(Ask, digits);
      sl    = NormalizeDouble(price - slDist, digits);
      tp    = (TakeProfitPips > 0.0) ? NormalizeDouble(price + tpDist, digits) : 0.0;
      arrow = clrBlue;
   }
   else // OP_SELL
   {
      price = NormalizeDouble(Bid, digits);
      sl    = NormalizeDouble(price + slDist, digits);
      tp    = (TakeProfitPips > 0.0) ? NormalizeDouble(price - tpDist, digits) : 0.0;
      arrow = clrRed;
   }

   //--- Seguranca extra: nunca enviar ordem sem stop loss.
   if(sl <= 0.0)
   {
      Print("ERRO: Stop Loss invalido calculado. Ordem NAO enviada.");
      return;
   }

   int slippagePoints = Slippage * (int)MathRound(pip / MarketInfo(symbol, MODE_POINT));

   int ticket = OrderSend(symbol, orderType, lot, price, slippagePoints,
                          sl, tp, "SmartTraderEA", MagicNumber, 0, arrow);

   if(ticket < 0)
   {
      int err = GetLastError();
      Print("Falha no OrderSend. Tipo=", orderType,
            " Lote=", DoubleToString(lot, 2),
            " Preco=", DoubleToString(price, digits),
            " SL=", DoubleToString(sl, digits),
            " TP=", DoubleToString(tp, digits),
            " Erro=", err, " (", ErrorDescription(err), ")");
   }
   else
   {
      Print("Ordem aberta. Ticket=", ticket,
            " Tipo=", (orderType == OP_BUY ? "BUY" : "SELL"),
            " Lote=", DoubleToString(lot, 2),
            " Preco=", DoubleToString(price, digits),
            " SL=", DoubleToString(sl, digits),
            " TP=", DoubleToString(tp, digits));
   }
}

//+------------------------------------------------------------------+
//| HasOpenPosition                                                   |
//| Verifica se ja existe posicao aberta para o simbolo+magic.        |
//+------------------------------------------------------------------+
bool HasOpenPosition(string symbol, int magic)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != symbol)         continue;
      if(OrderMagicNumber() != magic)     continue;
      if(OrderType() == OP_BUY || OrderType() == OP_SELL)
         return(true);
   }
   return(false);
}

//+------------------------------------------------------------------+
//| ManageTrailingStop                                               |
//| Trailing stop simples: arrasta o SL no sentido do lucro.          |
//+------------------------------------------------------------------+
void ManageTrailingStop()
{
   string symbol = Symbol();
   double pip    = PipPoint(symbol);
   int    digits = (int)MarketInfo(symbol, MODE_DIGITS);
   double trailDist = TrailingStopPips * pip;

   if(trailDist <= 0.0)
      return;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != symbol)             continue;
      if(OrderMagicNumber() != MagicNumber)   continue;

      if(OrderType() == OP_BUY)
      {
         double newSL = NormalizeDouble(Bid - trailDist, digits);
         // Move o SL apenas para cima e somente se melhorar a protecao atual
         if(newSL > OrderStopLoss() && newSL < Bid)
            ModifyOrderSL(OrderTicket(), newSL, OrderTakeProfit());
      }
      else if(OrderType() == OP_SELL)
      {
         double newSL = NormalizeDouble(Ask + trailDist, digits);
         // Move o SL apenas para baixo (ou quando ainda nao havia SL valido)
         if((newSL < OrderStopLoss() || OrderStopLoss() == 0.0) && newSL > Ask)
            ModifyOrderSL(OrderTicket(), newSL, OrderTakeProfit());
      }
   }
}

//+------------------------------------------------------------------+
//| ModifyOrderSL                                                     |
//| Wrapper para OrderModify com tratamento de erro.                  |
//+------------------------------------------------------------------+
void ModifyOrderSL(int ticket, double sl, double tp)
{
   if(!OrderModify(ticket, OrderOpenPrice(), sl, tp, 0, clrYellow))
   {
      int err = GetLastError();
      Print("Falha no OrderModify (trailing). Ticket=", ticket,
            " Erro=", err, " (", ErrorDescription(err), ")");
   }
}

//+------------------------------------------------------------------+
//| CloseTrade                                                        |
//| Fecha uma posicao de mercado pelo ticket (BUY/SELL).              |
//+------------------------------------------------------------------+
bool CloseTrade(int ticket)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET, MODE_TRADES))
   {
      Print("CloseTrade: nao foi possivel selecionar ticket ", ticket);
      return(false);
   }

   string symbol = OrderSymbol();
   int    digits = (int)MarketInfo(symbol, MODE_DIGITS);
   double pip    = PipPoint(symbol);
   int    slippagePoints = Slippage * (int)MathRound(pip / MarketInfo(symbol, MODE_POINT));

   double closePrice = 0.0;
   if(OrderType() == OP_BUY)
      closePrice = NormalizeDouble(MarketInfo(symbol, MODE_BID), digits);
   else if(OrderType() == OP_SELL)
      closePrice = NormalizeDouble(MarketInfo(symbol, MODE_ASK), digits);
   else
      return(false); // nao e posicao de mercado

   if(!OrderClose(ticket, OrderLots(), closePrice, slippagePoints, clrOrange))
   {
      int err = GetLastError();
      Print("Falha no OrderClose. Ticket=", ticket,
            " Erro=", err, " (", ErrorDescription(err), ")");
      return(false);
   }

   Print("Ordem fechada. Ticket=", ticket);
   return(true);
}

//+------------------------------------------------------------------+
//| CloseAllByMagic                                                   |
//| Fecha todas as posicoes do EA no simbolo atual (utilitario).      |
//+------------------------------------------------------------------+
void CloseAllByMagic()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != Symbol())          continue;
      if(OrderMagicNumber() != MagicNumber)  continue;
      if(OrderType() == OP_BUY || OrderType() == OP_SELL)
         CloseTrade(OrderTicket());
   }
}

//+------------------------------------------------------------------+
//| ErrorDescription                                                 |
//| Descricao curta dos erros de trade mais comuns do MQL4.           |
//+------------------------------------------------------------------+
string ErrorDescription(int code)
{
   switch(code)
   {
      case 0:    return("sem erro");
      case 1:    return("sem erro, mas resultado desconhecido");
      case 2:    return("erro comum");
      case 3:    return("parametros invalidos");
      case 4:    return("servidor de trade ocupado");
      case 5:    return("versao antiga do terminal");
      case 6:    return("sem conexao com servidor");
      case 8:    return("requisicoes muito frequentes");
      case 64:   return("conta bloqueada");
      case 65:   return("numero de conta invalido");
      case 128:  return("timeout da operacao");
      case 129:  return("preco invalido");
      case 130:  return("stops invalidos (muito proximos)");
      case 131:  return("volume invalido");
      case 132:  return("mercado fechado");
      case 133:  return("trade desabilitado");
      case 134:  return("dinheiro insuficiente");
      case 135:  return("preco mudou (requote)");
      case 136:  return("sem cotacoes (off quotes)");
      case 137:  return("corretora ocupada");
      case 138:  return("requote");
      case 139:  return("ordem bloqueada/sendo processada");
      case 145:  return("modificacao negada (ordem muito proxima do mercado)");
      case 146:  return("subsistema de trade ocupado");
      case 147:  return("uso de data de expiracao negado");
      case 148:  return("muitas ordens abertas/pendentes");
      default:   return("erro " + IntegerToString(code));
   }
}
//+------------------------------------------------------------------+
