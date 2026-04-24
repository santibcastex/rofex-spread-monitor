import os
import json
import requests
from anthropic import Anthropic
from datetime import datetime

IOL_USER = os.getenv("IOL_USER")
IOL_PASS = os.getenv("IOL_PASS")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

client = Anthropic()

# Spreads históricos (AJUSTA CON TUS DATOS REALES)
HISTORICAL_SPREADS = {
    "soja_nov_dic": {"promedio": 12, "min": 5, "max": 18},
    "soja_dic_mar": {"promedio": 10, "min": 3, "max": 16},
    "maiz_nov_dic": {"promedio": 8, "min": 2, "max": 14},
    "trigo_nov_dic": {"promedio": 6, "min": 1, "max": 12},
}

def get_iol_token():
    """Autentica en IOL"""
    url = "https://api.iol.com.ar/oauth2/token"
    payload = {
        "grant_type": "password",
        "username": IOL_USER,
        "password": IOL_PASS,
        "client_id": "eb1e5e6e-6ee2-495f-8fc3-be99cf37f3a8",
    }
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return r.json()["access_token"]
    except Exception as e:
        print(f"❌ Error autenticando IOL: {e}")
        return None

def get_rofex_price(token, symbol):
    """Obtiene precio de ROFEX"""
    url = f"https://api.iol.com.ar/api/v2/cotizaciones/{symbol}"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("ultimoPrecio")
    except Exception as e:
        print(f"⚠️ Error obteniendo precio {symbol}: {e}")
        return None

def fetch_all_spreads(token):
    """Obtiene precios y calcula spreads"""
    
    # SÍMBOLOS ROFEX EN IOL - AJUSTA CON LOS REALES
    symbols = {
        "soja_nov": "ROFEX:SOJANV26",
        "soja_dic": "ROFEX:SOJADI26",
        "soja_mar": "ROFEX:SOJAMAR27",
        "maiz_nov": "ROFEX:MAIZN26",
        "maiz_dic": "ROFEX:MAIZD26",
        "trigo_nov": "ROFEX:TRIGUN26",
        "trigo_dic": "ROFEX:TRIGUD26",
    }
    
    precios = {}
    for name, symbol in symbols.items():
        precio = get_rofex_price(token, symbol)
        precios[name] = precio
        if precio:
            print(f"✅ {name}: ${precio:.2f}")
        else:
            print(f"❌ {name}: sin datos")
    
    # Calcula spreads
    spreads = {}
    if precios["soja_nov"] and precios["soja_dic"]:
        spreads["soja_nov_dic"] = precios["soja_dic"] - precios["soja_nov"]
    if precios["soja_dic"] and precios["soja_mar"]:
        spreads["soja_dic_mar"] = precios["soja_mar"] - precios["soja_dic"]
    if precios["maiz_nov"] and precios["maiz_dic"]:
        spreads["maiz_nov_dic"] = precios["maiz_dic"] - precios["maiz_nov"]
    if precios["trigo_nov"] and precios["trigo_dic"]:
        spreads["trigo_nov_dic"] = precios["trigo_dic"] - precios["trigo_nov"]
    
    return spreads

def analyze_with_claude(spreads):
    """Claude analiza anomalías"""
    
    spread_text = "\n".join([
        f"{k}: ${v:.2f}" for k, v in spreads.items()
    ])
    
    historical_text = "\n".join([
        f"{k}: promedio ${v['promedio']}, rango ${v['min']}-${v['max']}"
        for k, v in HISTORICAL_SPREADS.items()
    ])
    
    prompt = f"""Sos un analista de spreads ROFEX.

SPREADS ACTUALES ($/tn):
{spread_text}

HISTÓRICO (últimos 6 meses):
{historical_text}

Analiza:
1. ¿Hay algún spread ANÓMALMENTE COMPRIMIDO? (< mínimo histórico)
2. ¿Hay algún spread ANÓMALMENTE AMPLIO? (> máximo histórico)
3. Para cada anomalía: operación sugerida y tamaño

Responde SOLO en JSON:
{{
  "anomalias": [
    {{
      "spread": "soja_nov_dic",
      "actual": 8.5,
      "promedio": 12,
      "desviacion_pct": -29,
      "tipo": "comprimido",
      "operacion": "COMPRAR Nov / VENDER Dic",
      "tamaño": "5 contratos"
    }}
  ],
  "resumen": "..."
}}

Si no hay anomalías, devuelve {{"anomalias": [], "resumen": "SIN OPORTUNIDAD"}}
"""
    
    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        text = response.content[0].text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0:
            return json.loads(text[start:end])
        return {"anomalias": [], "resumen": "Error parsing"}
    except Exception as e:
        print(f"❌ Error Claude: {e}")
        return {"anomalias": [], "resumen": "Error"}

def send_telegram(message):
    """Envía alerta a Telegram"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    })

def main():
    print(f"🚀 Monitor ROFEX {datetime.now().isoformat()}")
    
    token = get_iol_token()
    if not token:
        print("❌ Autenticación IOL falló")
        return
    
    spreads = fetch_all_spreads(token)
    print(f"Spreads: {spreads}")
    
    analisis = analyze_with_claude(spreads)
    print(f"Análisis: {json.dumps(analisis, indent=2)}")
    
    if analisis.get("anomalias"):
        msg = f"🎯 <b>OPORTUNIDAD ROFEX</b>\n\n{analisis['resumen']}\n\n"
        for a in analisis["anomalias"]:
            msg += f"<b>{a['spread']}</b>: {a['operacion']}\n"
        send_telegram(msg)
    else:
        print("ℹ️ Sin oportunidades")

if __name__ == "__main__":
    main()
