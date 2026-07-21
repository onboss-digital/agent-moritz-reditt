import os
import json
import sqlite3
import time
import random
import requests
import re
from openai import OpenAI
import google.generativeai as genai
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Carrega variáveis do arquivo .env
load_dotenv()

# As configurações agora são lidas do banco de dados (SQLite) dinamicamente.

def carregar_cookies():
    try:
        with open("cookies.json", "r") as f:
            cookies_list = json.load(f)
        return {cookie['name']: cookie['value'] for cookie in cookies_list}
    except Exception as e:
        print("ERRO: Não encontrei o cookies.json! Certifique-se de ter criado o arquivo.")
        return {}

# ==========================================
# BANCO DE DADOS
# ==========================================
def setup_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sent_messages (
            username TEXT PRIMARY KEY,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subreddit TEXT DEFAULT 'Desconhecido',
            keyword TEXT DEFAULT 'N/A',
            post_title TEXT DEFAULT 'N/A',
            message TEXT DEFAULT 'N/A',
            permalink TEXT DEFAULT '#'
        )
    ''')
    
    # Scripts de Migração para bancos antigos
    colunas = [row[1] for row in cursor.execute("PRAGMA table_info(sent_messages)").fetchall()]
    try:
        if 'subreddit' not in colunas:
            cursor.execute("ALTER TABLE sent_messages ADD COLUMN subreddit TEXT DEFAULT 'Desconhecido'")
        if 'keyword' not in colunas:
            cursor.execute("ALTER TABLE sent_messages ADD COLUMN keyword TEXT DEFAULT 'N/A'")
        if 'post_title' not in colunas:
            cursor.execute("ALTER TABLE sent_messages ADD COLUMN post_title TEXT DEFAULT 'N/A'")
        if 'message' not in colunas:
            cursor.execute("ALTER TABLE sent_messages ADD COLUMN message TEXT DEFAULT 'N/A'")
        if 'permalink' not in colunas:
            cursor.execute("ALTER TABLE sent_messages ADD COLUMN permalink TEXT DEFAULT '#'")
    except Exception as e:
        print(f"Aviso de migração de DB (sent_messages): {e}")
        pass
        
    cursor.execute('CREATE TABLE IF NOT EXISTS keywords (word TEXT PRIMARY KEY, category TEXT DEFAULT "creator")')
    
    colunas_kw = [row[1] for row in cursor.execute("PRAGMA table_info(keywords)").fetchall()]
    if 'category' not in colunas_kw:
        cursor.execute("ALTER TABLE keywords ADD COLUMN category TEXT DEFAULT 'creator'")
    cursor.execute('CREATE TABLE IF NOT EXISTS subreddits (name TEXT PRIMARY KEY)')
    
    cursor.execute('SELECT COUNT(*) FROM keywords')
    if cursor.fetchone()[0] == 0:
        default_kws = ["preciso trabalhar", "trabalho online", "renda extra", "ganhar dinheiro na internet", "sou freelancer", "dificuldade freelancer", "calote freelancer", "editor de vídeo", "design gráfico", "gestor de tráfego", "contratar freelancer", "preciso de editor de vídeo", "procurar designer", "agência de marketing", "dificuldade em", "problema com"]
        cursor.executemany('INSERT INTO keywords (word, category) VALUES (?, "creator")', [(kw,) for kw in default_kws])
        
    cursor.execute('SELECT COUNT(*) FROM subreddits')
    if cursor.fetchone()[0] == 0:
        default_subs = ["freelance", "SideHustle", "VagasArrombadas", "brdev", "empreendedorismo", "all"]
        cursor.executemany('INSERT INTO subreddits (name) VALUES (?)', [(s,) for s in default_subs])
        
    conn.commit()
    return conn

def usuario_ja_contatado(conn, username):
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM sent_messages WHERE username = ?', (username,))
    return cursor.fetchone() is not None

def registrar_envio(conn, username, subreddit, keyword, title, message, permalink):
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sent_messages (username, subreddit, keyword, post_title, message, permalink) VALUES (?, ?, ?, ?, ?, ?)", 
                       (username, subreddit, keyword, title, message, permalink))
        conn.commit()
    except Exception as e:
        print(f"Erro ao registrar envio no banco: {e}")

# ==========================================
# IA - GERAÇÃO DE MENSAGEM COM FALLBACK
# ==========================================
def atualizar_api_ativa(conn, api_name):
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS system_state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("INSERT OR REPLACE INTO system_state (key, value) VALUES ('active_api', ?)", (api_name,))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar state: {e}")

def gerar_mensagem_ia(conn, titulo, texto, categoria="creator"):
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )
    
    if categoria == "empresa":
        perfil_foco = "Ela conecta profissionais do mercado digital (como designers, editores de vídeo e gestores de tráfego) diretamente com empresas e clientes que precisam desses serviços todos os dias, de um jeito simples e prático. O melhor é que você pode buscar talentos e publicar suas necessidades de forma totalmente gratuita."
        convite = "Se tiver interesse em encontrar bons profissionais, me chama que te envio o link."
    else:
        perfil_foco = "Ela conecta profissionais do mercado digital, como designers, editores de vídeo, gestores de tráfego e outros freelancers, diretamente com clientes que procuram esses serviços todos os dias, de um jeito simples e prático. O melhor é que criar o perfil e publicar seus serviços é totalmente gratuito."
        convite = "Se tiver interesse, me chama que te envio o link para você cadastrar seus jobs."
    
    prompt = f"""
    Você é o criador da Lumpic, uma plataforma voltada para o mercado digital.
    Encontramos este post no Reddit de um potencial alvo:
    
    Título do Post: {titulo}
    Texto do Post: {texto}
    
    Escreva uma MENSAGEM PRIVADA descontraída, direta e persuasiva para essa pessoa.
    
    PONTOS OBRIGATÓRIOS PARA INCLUIR NO TEXTO (Faça soar natural e informal):
    1. Cita rapidamente a dor ou o assunto que a pessoa relatou no post para gerar conexão.
    2. Apresente a Lumpic como "o Airbnb dos serviços digitais".
    3. Foco Central (Use essas informações): "{perfil_foco}"
    4. Finalize dizendo: "{convite}"
    
    REGRA DE GÊNERO IMPORTANTÍSSIMA:
    - Analise o texto e o título do post para identificar o GÊNERO da pessoa (pela forma como ela escreve, ex: "estou cansada", "sou nova aqui").
    - Se for MULHER, NÃO use gírias masculinas em hipótese alguma (nada de "cara", "mano", "velho").
    - Se NÃO CONSEGUIR IDENTIFICAR o gênero com certeza, use uma saudação NEUTRA (Ex: "Opa, tudo bem?", "Fala aí!", "Oi!").
    - Só use "Opa cara" se tiver certeza que é homem.
    
    EXEMPLO DO TOM DE VOZ IDEAL E ESTRUTURA (Varie as palavras a cada mensagem gerada para não ser considerado Spam):
    "[Saudação de acordo com o gênero]! Tava lendo seu post sobre a dificuldade de [assunto] e entendo bem essa situação. Queria te apresentar a Lumpic, que funciona como o Airbnb dos serviços digitais. {perfil_foco} {convite}"
    
    REGRAS RÍGIDAS:
    1. É TOTALMENTE PROIBIDO usar emojis.
    2. Nunca pareça formal ou engessado.
    3. Retorne APENAS o texto final da mensagem.
    """
    
    # 1. Tentar OpenRouter Primeiro
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash:free",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        atualizar_api_ativa(conn, 'OpenRouter')
        print("[SISTEMA IA] Mensagem gerada via OpenRouter (gemini-2.5-flash).")
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[AVISO IA] Falha no OpenRouter: {e}. Iniciando Fallback para Gemini Nativo...")
        
    # 2. Fallback para Google Gemini Nativo
    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel('gemini-2.5-flash')
        resposta = model.generate_content(prompt)
        atualizar_api_ativa(conn, 'Gemini')
        print("[SISTEMA IA] Mensagem gerada via Google Gemini Nativo.")
        return resposta.text.strip()
    except Exception as e2:
        print(f"[ERRO IA FATAL] Ambas as APIs falharam (OpenRouter e Gemini Nativo). Erro Gemini: {e2}")
        return "Olá! Vi seu post e gostaria de apresentar a Lumpic, uma plataforma grátis de freelancing focada no mercado digital. Se tiver interesse, me mande uma mensagem!"


# ==========================================
# PLAYWRIGHT - ENVIO REAL
# ==========================================
def enviar_mensagem_playwright(username, assunto, mensagem):
    print(f"Abrindo navegador para enviar mensagem para u/{username}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
        
        # Carrega a sessão salva
        context = browser.new_context()
        
        # Injeta os nossos cookies que estão no cookies.json para o navegador do Playwright
        cookies_dict = carregar_cookies()
        if cookies_dict:
            playwright_cookies = [{"name": k, "value": v, "domain": ".reddit.com", "path": "/"} for k, v in cookies_dict.items()]
            context.add_cookies(playwright_cookies)

        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        try:
            # Vamos usar o sistema de Mensagem Privada clássico do Reddit (mais estável para automação que o Chat)
            page.goto(f"https://www.reddit.com/message/compose/?to={username}")
            
            # Verifica se o Reddit derrubou a sessão por causa do IP da Nuvem
            if "login" in page.url or "register" in page.url:
                print("  -> [ERRO FATAL] O Reddit deslogou a nossa sessão por segurança (novo IP da VPS).")
                print("  -> É necessário logar novamente gerando um novo cookies.json pelo seu computador.")
                import os
                os.makedirs("erros", exist_ok=True)
                page.screenshot(path=f"erros/erro_login_reddit_{username}.png")
                return False
            
            # PREENCHE O ASSUNTO
            print("  -> Preenchendo assunto...")
            try:
                # O Reddit agora usa componentes customizados (faceplate). Vamos forçar a injeção do texto.
                page.locator('input[name="subject"], input[name="message-title"], faceplate-text-input[name="message-title"]').first.fill(assunto, timeout=5000, force=True)
            except:
                # Fallback: clica forçadamente e digita
                page.locator('faceplate-text-input[name="message-title"]').first.click(timeout=5000, force=True)
                page.keyboard.type(assunto)
                
            time.sleep(random.uniform(1.0, 2.5)) # Delay humano
            
            # PREENCHE A MENSAGEM
            print("  -> Preenchendo mensagem...")
            try:
                page.locator('textarea[name="text"], textarea[name="message-body"], faceplate-textarea-input[name="message-body"]').first.fill(mensagem, timeout=3000, force=True)
            except:
                try:
                    page.locator('faceplate-textarea-input').first.click(timeout=2000, force=True)
                    page.keyboard.type(mensagem)
                except:
                    print("     [!] Usando navegação por teclado (TAB) para chegar na mensagem...")
                    # O cursor estava no Assunto. Pressionar TAB deve ir para a Mensagem.
                    page.keyboard.press("Tab")
                    page.keyboard.type(mensagem)
                
            time.sleep(random.uniform(1.5, 3.5)) # Delay humano
            
            # CLICA EM ENVIAR
            print("  -> Clicando em enviar...")
            try:
                page.locator('button[type="submit"], button:has-text("Enviar"), button:has-text("Send")').first.click(timeout=3000, force=True)
            except:
                print("     [!] Usando navegação por teclado (TAB) para chegar no botão Enviar...")
                page.keyboard.press("Tab")
                page.keyboard.press("Enter")
                # Caso haja formatação entre a mensagem e o botão, tenta mais um TAB
                time.sleep(1)
                page.keyboard.press("Tab")
                page.keyboard.press("Enter")
            
            # Aguarda um pouquinho para garantir o envio
            time.sleep(3)
            print(f"[SUCESSO] Mensagem enviada para u/{username}!")
            return True
            
        except Exception as e:
            print(f"[ERRO] Falha ao enviar mensagem pelo navegador: {e}")
            try:
                import os
                os.makedirs("erros", exist_ok=True)
                page.screenshot(path=f"erros/erro_reddit_{username}.png")
                with open(f"erros/erro_reddit_{username}.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                print(f"-> Salvei uma foto e o código fonte na pasta 'erros/' para debug!")
            except:
                pass
            return False
        finally:
            browser.close()

# ==========================================
# MOTOR PRINCIPAL
# ==========================================
def main():
    print("Iniciando Robô Moritz (MODO DE PRODUÇÃO)...")
    
    while True:
        conn = setup_db()
        cursor = conn.cursor()
        cursor.execute('SELECT word, category FROM keywords')
        PALAVRAS_CHAVE = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.execute('SELECT name FROM subreddits')
        SUBREDDITS = [row[0] for row in cursor.fetchall()]
        
        cookies_dict = carregar_cookies()
        
        if not PALAVRAS_CHAVE or not SUBREDDITS:
            print("Erro: Nenhuma palavra-chave ou subreddit configurado. Adicione pelo Painel de Controle.")
            time.sleep(60) # Espera 1 minuto e tenta ler de novo
            continue
            
        # === SISTEMA DE SAÚDE DA CONTA (SAFE-LIMIT) ===
        cursor.execute("SELECT COUNT(*) FROM sent_messages WHERE sent_at >= datetime('now', '-1 day')")
        daily_count = cursor.fetchone()[0]
        limite_diario = 30
        
        if daily_count >= limite_diario:
            print(f"[ALERTA DE SAÚDE] A conta já enviou {daily_count} mensagens nas últimas 24h.")
            print("Operação PAUSADA automaticamente para proteger contra Banimento.")
            print("O robô vai dormir por 4 horas e checar novamente...")
            time.sleep(4 * 60 * 60) # Dorme 4 horas
            continue
        # ===============================================
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'}
        
        alvos_encontrados = []
        
        # FASE 1: Leitura e Descoberta
        for sub in SUBREDDITS:
            print(f"\nBuscando no subreddit: r/{sub}...")
            # Aumentado para 100 para puxar histórico antigo (até semanas atrás dependendo do fórum)
            url = f"https://www.reddit.com/r/{sub}/new.json?limit=100"
            
            try:
                response = requests.get(url, headers=headers, cookies=cookies_dict)
                if response.status_code != 200:
                    print(f"Erro ao acessar r/{sub}. Status: {response.status_code}")
                    continue
                    
                dados = response.json()
                if 'data' in dados and 'children' in dados['data']:
                    for post in dados['data']['children']:
                        info = post['data']
                        autor = info.get('author', '')
                        titulo = info.get('title', '')
                        texto = info.get('selftext', '')
                        permalink = info.get('permalink', '#')
                        
                        if autor == '[deleted]' or autor == 'AutoModerator':
                            continue
                            
                        conteudo_completo = (titulo + " " + texto).lower()
                        match_word = next((kw for kw in PALAVRAS_CHAVE.keys() if kw.lower() in conteudo_completo), None)
                        
                        if match_word:
                            if usuario_ja_contatado(conn, autor):
                                continue # Pula silenciosamente quem já recebeu
                                
                            match_category = PALAVRAS_CHAVE[match_word]
                                
                            print(f"[!] ALVO ENCONTRADO: u/{autor} (Palavra: '{match_word}' | Categoria: {match_category})")
                            alvos_encontrados.append({
                                'autor': autor,
                                'titulo': titulo,
                                'texto': texto,
                                'assunto': f"Sobre o seu post no r/{sub}",
                                'sub': sub,
                                'match': match_word,
                                'categoria': match_category,
                                'permalink': permalink
                            })
            except Exception as e:
                print(f"Erro no subreddit {sub}: {e}")
                
        # FASE 2: Geração e Envio
        if not alvos_encontrados:
            print("\nNenhum alvo novo encontrado neste ciclo.")
            print("O robô vai aguardar 30 minutos antes de vasculhar o Reddit novamente...")
            time.sleep(30 * 60) # 30 minutos de pausa
            continue # Volta pro início do While True
            
        print(f"\nTotal de novos alvos encontrados: {len(alvos_encontrados)}")
        print("Iniciando rotina de envio com atrasos de segurança (Anti-Spam)...\n")
        
        for alvo in alvos_encontrados:
            autor = alvo['autor']
            print(f"\nGerando mensagem para u/{autor}...")
            mensagem = gerar_mensagem_ia(conn, alvo['titulo'], alvo['texto'], alvo['categoria'])
            
            print(f"Abrindo navegador para enviar mensagem para u/{autor}...")
            sucesso = enviar_mensagem_playwright(autor, alvo['assunto'], mensagem)
            
            if sucesso:
                registrar_envio(conn, autor, alvo['sub'], alvo['match'], alvo['titulo'], mensagem, alvo['permalink'])
                
                # SISTEMA ANTI-SPAM: Delay enorme entre uma mensagem e outra (2 a 4 minutos)
                tempo_espera = random.randint(120, 240)
                print(f"[SUCESSO] Mensagem enviada! Aguardando {tempo_espera} segundos...")
                time.sleep(tempo_espera)
            else:
                print(f"[ERRO] Falha ao enviar para u/{autor}.")
                time.sleep(30)
                
        print("\n[SISTEMA] Ciclo de envios finalizado. Entrando em modo de vigília.")
        print("O robô vai aguardar 30 minutos antes de buscar novos posts...")
        time.sleep(30 * 60) # 30 minutos antes do próximo ciclo

if __name__ == "__main__":
    main()
