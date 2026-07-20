import os
import google.generativeai as genai
from dotenv import load_dotenv

# Carrega a chave do .env
load_dotenv()
chave = os.getenv("GEMINI_API_KEY")

print(f"Testando a chave: {chave[:10]}...{chave[-5:]}")

genai.configure(api_key=chave)

try:
    print("\nBuscando modelos de IA disponíveis para essa chave do Google...")
    modelos_encontrados = False
    
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
            modelos_encontrados = True
            
    if not modelos_encontrados:
        print("Nenhum modelo de geração de texto foi encontrado para essa chave.")
        
except Exception as e:
    print(f"\nERRO DE AUTENTICAÇÃO NO GOOGLE: {e}")
