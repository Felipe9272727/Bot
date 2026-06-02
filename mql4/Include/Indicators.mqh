//+------------------------------------------------------------------+
//|                                                  Indicators.mqh   |
//|        Sinais de analise tecnica puros (sem estado de conta)      |
//|        Contrato: docs/ARQUITETURA.md                              |
//+------------------------------------------------------------------+
#property strict

//--- Parametros configuraveis dos indicadores (inputs do EA).
//    Sao declarados como 'extern' para que possam ser sobrescritos
//    pelos inputs do Expert Advisor que inclui este arquivo.
//    Se o EA ja declarar variaveis com o mesmo nome, ele deve passar
//    os periodos atraves desses externs (ver SmartTraderEA.mq4).
extern int EMA_Fast   = 9;   // Periodo da EMA rapida
extern int EMA_Slow   = 21;  // Periodo da EMA lenta
extern int RSI_Period = 14;  // Periodo do RSI

//--- Niveis do filtro RSI (constantes da estrategia)
#define RSI_OVERBOUGHT 70.0  // Acima disso = sobrecomprado (nao comprar)
#define RSI_OVERSOLD   30.0  // Abaixo disso = sobrevendido (nao vender)

//+------------------------------------------------------------------+
//| GetEMA                                                            |
//| Le a EMA (MODE_EMA) sobre o preco de fechamento no candle ja      |
//| fechado (shift 1) para evitar repintura.                          |
//+------------------------------------------------------------------+
double GetEMA(string symbol, int timeframe, int period)
{
   //  iMA(symbol, timeframe, period, ma_shift, ma_method, applied_price, shift)
   //  shift = 1  -> candle fechado anterior (nao o candle em formacao)
   return(iMA(symbol, timeframe, period, 0, MODE_EMA, PRICE_CLOSE, 1));
}

//+------------------------------------------------------------------+
//| GetEMA com shift explicito (uso interno para detectar cruzamento) |
//+------------------------------------------------------------------+
double GetEMAShift(string symbol, int timeframe, int period, int shift)
{
   return(iMA(symbol, timeframe, period, 0, MODE_EMA, PRICE_CLOSE, shift));
}

//+------------------------------------------------------------------+
//| GetRSI                                                            |
//| Le o RSI no candle ja fechado (shift 1) para evitar repintura.    |
//+------------------------------------------------------------------+
double GetRSI(string symbol, int timeframe, int period)
{
   //  iRSI(symbol, timeframe, period, applied_price, shift)
   return(iRSI(symbol, timeframe, period, PRICE_CLOSE, 1));
}

//+------------------------------------------------------------------+
//| GetTechnicalSignal                                               |
//| Estrategia: cruzamento de EMA rapida sobre EMA lenta, confirmado  |
//| por filtro RSI.                                                   |
//|                                                                   |
//| - COMPRA (1): a EMA rapida cruzou para CIMA da lenta entre o      |
//|   candle 2 e o candle 1, e o RSI NAO esta sobrecomprado (<70).    |
//| - VENDE (-1): a EMA rapida cruzou para BAIXO da lenta entre o     |
//|   candle 2 e o candle 1, e o RSI NAO esta sobrevendido (>30).     |
//| - NEUTRO (0): nenhuma condicao satisfeita.                        |
//|                                                                   |
//| O cruzamento e calculado comparando shift 1 vs shift 2 (ambos     |
//| candles fechados) -> nao repinta.                                 |
//+------------------------------------------------------------------+
int GetTechnicalSignal(string symbol, int timeframe)
{
   //--- EMAs nos dois ultimos candles fechados
   double emaFastPrev = GetEMAShift(symbol, timeframe, EMA_Fast, 2); // candle 2
   double emaFastNow  = GetEMAShift(symbol, timeframe, EMA_Fast, 1); // candle 1
   double emaSlowPrev = GetEMAShift(symbol, timeframe, EMA_Slow, 2); // candle 2
   double emaSlowNow  = GetEMAShift(symbol, timeframe, EMA_Slow, 1); // candle 1

   //--- RSI no candle fechado (filtro de confirmacao)
   double rsi = GetRSI(symbol, timeframe, RSI_Period);

   //--- Protecao: se algum valor de indicador falhar, nao operar
   if(emaFastPrev == 0.0 || emaFastNow == 0.0 ||
      emaSlowPrev == 0.0 || emaSlowNow == 0.0)
      return(0);

   //--- Deteccao de cruzamento (rapida vs lenta)
   bool crossUp   = (emaFastPrev <= emaSlowPrev) && (emaFastNow > emaSlowNow);
   bool crossDown = (emaFastPrev >= emaSlowPrev) && (emaFastNow < emaSlowNow);

   //--- Sinal de COMPRA: cruzamento de alta + RSI nao sobrecomprado
   if(crossUp && rsi < RSI_OVERBOUGHT)
      return(1);

   //--- Sinal de VENDA: cruzamento de baixa + RSI nao sobrevendido
   if(crossDown && rsi > RSI_OVERSOLD)
      return(-1);

   //--- Sem sinal valido
   return(0);
}
//+------------------------------------------------------------------+
