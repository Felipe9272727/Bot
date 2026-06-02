//+------------------------------------------------------------------+
//|                                                    AIBridge.mqh    |
//|        Ponte HTTP com o servico de IA externo (WebRequest)        |
//|        Contrato: docs/ARQUITETURA.md                              |
//+------------------------------------------------------------------+
//                                                                    |
//  IMPORTANTE - declaracao de inputs (UseAI / AIServerURL):          |
//                                                                    |
//  O contrato (ARQUITETURA.md) define que o EA possui os inputs       |
//  'UseAI' e 'AIServerURL'. Para evitar o erro "variable already      |
//  defined" quando o EA tambem os declara, este include NAO os        |
//  redeclara incondicionalmente.                                      |
//                                                                    |
//  Padrao adotado: guard com #ifndef. Se o EA quiser ser o "dono"     |
//  desses inputs (recomendado, pois assim aparecem na janela de       |
//  inputs do EA), basta definir o macro AIBRIDGE_INPUTS_EXTERNAL      |
//  ANTES de incluir este arquivo:                                     |
//                                                                    |
//     extern bool   UseAI       = true;                              |
//     extern string AIServerURL = "http://127.0.0.1:5000/signal";    |
//     #define AIBRIDGE_INPUTS_EXTERNAL                               |
//     #include <AIBridge.mqh>                                        |
//                                                                    |
//  Caso o macro NAO esteja definido, este include declara os inputs   |
//  por conta propria (modo standalone / testes).                      |
//+------------------------------------------------------------------+
#property strict

//--- Inputs ligados a IA. Veja a nota acima sobre AIBRIDGE_INPUTS_EXTERNAL.
#ifndef AIBRIDGE_INPUTS_EXTERNAL
   extern bool   UseAI       = true;                              // Liga/desliga o uso da IA
   extern string AIServerURL = "http://127.0.0.1:5000/signal";    // URL do servico (whitelist do MT4!)
#endif

//--- Timeout da requisicao HTTP (sempre declarado aqui).
extern int    AITimeoutMs = 800;   // Timeout do WebRequest em milissegundos

//--- Confianca minima exposta para o EA consultar, se desejar.
//    Mantida como variavel global para leitura externa apos GetAISignal.
double g_LastAIConfidence = 0.0;   // Ultima confianca retornada pela IA (0..1)

//+------------------------------------------------------------------+
//| JsonExtractNumber                                                |
//| Parser minimalista: procura a chave "key" no texto JSON e le o   |
//| numero que vem logo apos os dois pontos. Robusto a espacos.      |
//| Retorna true e preenche 'value' se conseguir; false caso         |
//| contrario. Suporta inteiros, decimais e sinal negativo.          |
//+------------------------------------------------------------------+
bool JsonExtractNumber(string json, string key, double &value)
{
   //--- Procura o padrao "key"
   string needle = "\"" + key + "\"";
   int pos = StringFind(json, needle);
   if(pos < 0)
      return(false);

   //--- Avanca apos a chave
   pos += StringLen(needle);
   int len = StringLen(json);

   //--- Procura os dois pontos ':' que separam chave de valor
   while(pos < len)
   {
      int c = StringGetChar(json, pos);
      if(c == ':')
      {
         pos++;
         break;
      }
      //--- Espacos sao tolerados; qualquer outro caractere = formato inesperado
      if(c == ' ' || c == '\t' || c == '\r' || c == '\n')
      {
         pos++;
         continue;
      }
      return(false);
   }

   //--- Pula espacos apos os dois pontos
   while(pos < len)
   {
      int cc = StringGetChar(json, pos);
      if(cc == ' ' || cc == '\t' || cc == '\r' || cc == '\n')
      {
         pos++;
         continue;
      }
      break;
   }

   //--- Le o numero: opcional '-', digitos, ponto decimal
   string numStr = "";
   bool   started = false;
   while(pos < len)
   {
      int ch = StringGetChar(json, pos);
      bool isDigit = (ch >= '0' && ch <= '9');
      bool isSign  = (ch == '-' || ch == '+') && !started;
      bool isDot   = (ch == '.');

      if(isDigit || isSign || isDot)
      {
         numStr  += CharToStr((uchar)ch);
         started  = true;
         pos++;
         continue;
      }
      break; // fim do numero
   }

   if(!started || StringLen(numStr) == 0)
      return(false);

   value = StrToDouble(numStr);
   return(true);
}

//+------------------------------------------------------------------+
//| BuildFeaturesJson                                                |
//| Monta o corpo JSON da requisicao com features simples de mercado: |
//| symbol, timeframe e um objeto features {rsi, ema_fast, ema_slow,  |
//| price, spread}. Os indicadores sao calculados aqui mesmo via      |
//| iRSI/iMA/MarketInfo para tornar o include autossuficiente.        |
//+------------------------------------------------------------------+
string BuildFeaturesJson(string symbol, int timeframe)
{
   //--- Indicadores no candle ja fechado (shift 1) para nao repintar
   double rsi      = iRSI(symbol, timeframe, 14, PRICE_CLOSE, 1);
   double emaFast  = iMA(symbol, timeframe, 9,  0, MODE_EMA, PRICE_CLOSE, 1);
   double emaSlow  = iMA(symbol, timeframe, 21, 0, MODE_EMA, PRICE_CLOSE, 1);
   double price    = MarketInfo(symbol, MODE_BID);

   //--- Spread em pips: (Ask-Bid)/point, ajustado p/ 3/5 digitos
   double point  = MarketInfo(symbol, MODE_POINT);
   int    digits = (int)MarketInfo(symbol, MODE_DIGITS);
   double pip    = (digits == 3 || digits == 5) ? point * 10.0 : point;
   double spread = 0.0;
   if(pip > 0.0)
      spread = (MarketInfo(symbol, MODE_ASK) - MarketInfo(symbol, MODE_BID)) / pip;

   //--- Monta o JSON manualmente (MQL4 nao tem serializador nativo)
   string json = "{";
   json += "\"symbol\":\"" + symbol + "\",";
   json += "\"timeframe\":" + IntegerToString(timeframe) + ",";
   json += "\"features\":{";
   json += "\"rsi\":"      + DoubleToStr(rsi, 4)     + ",";
   json += "\"ema_fast\":" + DoubleToStr(emaFast, digits) + ",";
   json += "\"ema_slow\":" + DoubleToStr(emaSlow, digits) + ",";
   json += "\"price\":"    + DoubleToStr(price, digits)   + ",";
   json += "\"spread\":"   + DoubleToStr(spread, 2);
   json += "}";
   json += "}";

   return(json);
}

//+------------------------------------------------------------------+
//| GetAISignal                                                      |
//| Consulta o servico de IA via WebRequest (POST JSON).             |
//| Retorna 1 / -1 / 0 conforme a convencao de sinais.              |
//| FAIL-SAFE: qualquer erro (rede, timeout, parse) retorna 0.       |
//| Se UseAI == false, retorna 0 imediatamente sem tocar a rede.    |
//+------------------------------------------------------------------+
int GetAISignal(string symbol, int timeframe)
{
   //--- Reseta a ultima confianca conhecida
   g_LastAIConfidence = 0.0;

   //--- IA desligada: nao chama a rede
   if(!UseAI)
      return(0);

   //--- URL nao configurada => nao opera com IA
   if(StringLen(AIServerURL) == 0)
   {
      Print("GetAISignal: AIServerURL vazio - IA ignorada (retornando 0).");
      return(0);
   }

   //--- Monta o corpo da requisicao
   string body = BuildFeaturesJson(symbol, timeframe);

   //--- Cabecalhos HTTP
   string headers = "Content-Type: application/json\r\n";

   //--- Converte o corpo para array de bytes (uchar).
   //    StringToCharArray adiciona um terminador '\0'; removemos esse
   //    byte final para nao enviar lixo no corpo POST.
   uchar postData[];
   int   bodyLen = StringToCharArray(body, postData, 0, StringLen(body));
   //    'bodyLen' aqui ja e o numero de bytes uteis (sem o terminador),
   //    pois limitamos a copia a StringLen(body).
   ArrayResize(postData, bodyLen);

   //--- Buffers de retorno
   uchar  result[];
   string resultHeaders = "";

   //--- Executa o POST. WebRequest retorna o codigo HTTP (>=0) ou -1 em erro.
   ResetLastError();
   int httpCode = WebRequest("POST", AIServerURL, headers, AITimeoutMs,
                             postData, result, resultHeaders);

   //--- Erro de transporte (URL fora da whitelist, sem rede, timeout, etc.)
   if(httpCode == -1)
   {
      int err = GetLastError();
      Print("GetAISignal: WebRequest falhou (erro ", err, "). ",
            "Verifique se '", AIServerURL,
            "' esta na whitelist (Ferramentas>Opcoes>Expert Advisors). Retornando 0.");
      return(0);
   }

   //--- HTTP diferente de 200 OK => fail-safe
   if(httpCode != 200)
   {
      Print("GetAISignal: HTTP ", httpCode, " do servico de IA. Retornando 0.");
      return(0);
   }

   //--- Converte a resposta (bytes) de volta para string
   string response = CharArrayToString(result, 0, ArraySize(result));

   //--- Parse do campo "signal" (inteiro)
   double signalVal = 0.0;
   if(!JsonExtractNumber(response, "signal", signalVal))
   {
      Print("GetAISignal: nao foi possivel ler 'signal' da resposta: ",
            response, ". Retornando 0.");
      return(0);
   }

   //--- Parse do campo "confidence" (double) - opcional, nao bloqueia
   double confVal = 0.0;
   if(JsonExtractNumber(response, "confidence", confVal))
      g_LastAIConfidence = confVal;

   //--- Normaliza o sinal para 1 / -1 / 0
   int signal = (int)MathRound(signalVal);
   if(signal > 0)  return(1);
   if(signal < 0)  return(-1);
   return(0);
}
//+------------------------------------------------------------------+
