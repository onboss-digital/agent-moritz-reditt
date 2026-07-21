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
    
    # Novas tabelas de Inteligência
    cursor.execute('CREATE TABLE IF NOT EXISTS negative_keywords (word TEXT PRIMARY KEY, added_by_ia BOOLEAN DEFAULT 0)')
    cursor.execute('CREATE TABLE IF NOT EXISTS suggested_subreddits (name TEXT PRIMARY KEY, status TEXT DEFAULT "pending")')
    
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
# IA - GERAÇÃO DE MENSAGEM COM FALLBACK E FILTROS
# ==========================================
def atualizar_api_ativa(conn, api_name):
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS system_state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("INSERT OR REPLACE INTO system_state (key, value) VALUES ('active_api', ?)", (api_name,))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar state: {e}")

def analisar_intencao_e_aprender(conn, titulo, texto, keyword):
    """ Filtro de Intenção e Blacklist Automática """
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )
    
    prompt = f"""
Analise o post do Reddit abaixo para saber se ele é uma OPORTUNIDADE DE PROSPECÇÃO VÁLIDA para a plataforma Lumpic (um site para freelancers digitais tipo design, vídeo, tráfego, etc, e pessoas buscando contratá-los).

Título: {titulo}
Texto: {texto}

É VÁLIDO SE: A pessoa claramente quer contratar um freelancer digital OU a pessoa claramente está oferecendo serviços digitais / buscando clientes.
É INVÁLIDO SE: For apenas um desabafo (ex: fui roubado), for vaga presencial (ex: CLT em SP), for de graça/voluntário, ou não tiver nenhuma relação com serviços digitais freelance.

Se for INVÁLIDO, identifique 1 ou 2 palavras do texto que entregam o motivo (ex: "presencial", "clt", "voluntario", "golpe", "desabafo"). Retorne apenas UMA palavra-chave principal ou expressão curta.

Responda EXATAMENTE neste formato JSON e nada mais:
{{"valido": true ou false, "palavra_negativa": "palavra_aqui" ou null}}
    """
    
    try:
        response = client.chat.completions.create(
            model="meta-llama/llama-3.3-70b-instruct:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        
        # Extrair JSON da resposta
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            dados = json.loads(match.group())
            is_valido = dados.get('valido', True)
            palavra_negativa = dados.get('palavra_negativa')
            
            if not is_valido and palavra_negativa:
                # Aprender: Adicionar na blacklist
                palavra_limpa = palavra_negativa.lower().strip()
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO negative_keywords (word, added_by_ia) VALUES (?, 1)", (palavra_limpa,))
                conn.commit()
                print(f"     [IA APRENDEU] Post descartado. Adicionou '{palavra_limpa}' à Blacklist automática.")
                return False
            return is_valido
    except Exception as e:
        print(f"     [AVISO IA] Falha ao analisar intenção: {e}. Permitindo o post por segurança.")
    
    return True

def gerar_mensagem_ia(conn, titulo, texto, categoria="creator"):
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )
    
    if categoria == "empresa":
        perfil_foco = "Tem uma plataforma chamada Lumpic que conecta profissionais do mercado digital (como designers e editores de vídeo) diretamente com pessoas que precisam desses serviços. É de graça pra postar o que você precisa."
        convite = "Dá uma olhada depois, acho que pode te ajudar a achar alguém bom."
    else:
        perfil_foco = "Tem um site novo chamado Lumpic que funciona tipo um Airbnb pra serviços digitais. Dá pra criar um perfil de graça e oferecer seus trampos pra quem tá procurando."
        convite = "Se quiser dar uma olhada depois, acho que pode te ajudar a arrumar mais freelas."
    
    prompt = f"""
    Você é um usuário casual e prestativo do Reddit. Você descobriu recentemente uma plataforma incrível e quer indicá-la.
    Encontramos este post no Reddit:
    
    Título: {titulo}
    Texto: {texto}
    
    Escreva uma MENSAGEM PRIVADA super curta, natural e direta (estilo WhatsApp) para essa pessoa.
    
    ESTRUTURA OBRIGATÓRIA DA MENSAGEM (Siga isso à risca, mas varie as palavras):
    1. Saudação + Conexão rápida: "Opa, vi seu post sobre [assunto] e..."
    2. A Indicação (Airbnb): Diga que conhece um site (Lumpic) que funciona tipo um Airbnb para serviços digitais.
    3. O Diferencial: Destaque que o cadastro é 100% de graça, leva 2 minutos, e que já tem clientes/freelancers procurando fechar negócio lá ativamente.
    4. Encerramento: Uma despedida curta que não pareça que você está vendendo algo.
    
    REGRA DE GÊNERO:
    - Identifique o gênero da pessoa pelo texto (ex: "estou cansada"). Se for mulher, NÃO use gírias masculinas. Se for incerto, use gênero neutro (ex: "Tudo bem?").
    
    REGRAS RÍGIDAS:
    - MAXIMO DE 3 a 4 LINHAS. Ninguém gosta de ler textão.
    - É TOTALMENTE PROIBIDO usar emojis.
    - É TOTALMENTE PROIBIDO parecer o dono da plataforma ou um robô vendedor.
    - Retorne APENAS o texto da mensagem.
    """
    
    # 1. Tentar OpenRouter Primeiro
    try:
        response = client.chat.completions.create(
            model="meta-llama/llama-3.3-70b-instruct:free",
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
        
        # Fallbacks de emergência variados para não repetir a mesma mensagem caso a IA fique fora do ar muito tempo
        mensagens_emergencia_creator = [
            "Opa, tudo bem? Vi seu post agora há pouco. Dá uma olhada numa plataforma chamada Lumpic, ela conecta freelancers com quem precisa de serviço. Pode te ajudar a arrumar uns trampos novos, o cadastro é de graça.",
            "Fala aí! Lendo o que você postou, lembrei de um site que uso chamado Lumpic. É focado em freelas no digital (design, vídeo, etc). Recomendo dar uma checada, me ajudou bastante recentemente.",
            "Oi! Vi seu post e lembrei da Lumpic. É uma plataforma pra freelancers conseguirem jobs e divulgarem portfólio. Não custa nada criar o perfil lá, acho que vale a pena pra você testar."
        ]
        
        mensagens_emergencia_empresa = [
            "Opa, vi que você tá procurando profissionais. Tem um site chamado Lumpic que é muito bom pra encontrar freelancers (design, tráfego, vídeo). Dá pra postar a vaga de graça lá.",
            "Tudo bem? Sobre o seu post, recomendo dar uma olhada na Lumpic. É uma plataforma que junta vários freelancers, fica bem mais fácil achar gente capacitada pro que você precisa.",
            "Fala aí! Se ainda estiver precisando, tenta buscar na Lumpic. É um site novo pra serviços digitais, tipo um classificados de freelas. É bem prático pra achar bons profissionais."
        ]
        
        if categoria == "empresa":
            msg_final = random.choice(mensagens_emergencia_empresa)
        else:
            msg_final = random.choice(mensagens_emergencia_creator)
            
        return msg_final


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
        
        cursor.execute('SELECT word FROM negative_keywords')
        BLACKLIST = [row[0].lower() for row in cursor.fetchall()]
        
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
                        created_utc = info.get('created_utc', 0)
                        num_comments = info.get('num_comments', 0)
                        
                        if autor == '[deleted]' or autor == 'AutoModerator':
                            continue
                            
                        # Filtro de Concorrência (Vagas Frescas)
                        if num_comments > 20:
                            continue
                            
                        # Ignora posts com mais de 30 dias (2592000 segundos)
                        if time.time() - created_utc > 2592000:
                            continue
                            
                        conteudo_completo = (titulo + " " + texto).lower()
                        
                        # Filtro de Blacklist Local
                        if any(bw in conteudo_completo for bw in BLACKLIST):
                            continue
                        
                        match_word = next((kw for kw in PALAVRAS_CHAVE.keys() if kw.lower() in conteudo_completo), None)
                        
                        if match_word:
                            if usuario_ja_contatado(conn, autor):
                                continue # Pula silenciosamente quem já recebeu
                                
                            print(f"[?] Analisando intenção do post de u/{autor} com IA... (Palavra: '{match_word}')")
                            
                            if analisar_intencao_e_aprender(conn, titulo, texto, match_word):
                                match_category = PALAVRAS_CHAVE[match_word]
                                print(f"[!] ALVO APROVADO: u/{autor} (Categoria: {match_category})")
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
                            else:
                                # Atualiza a blacklist para o próximo loop em tempo real
                                cursor.execute('SELECT word FROM negative_keywords')
                                BLACKLIST = [row[0].lower() for row in cursor.fetchall()]
            except Exception as e:
                print(f"Erro no subreddit {sub}: {e}")
                
        # FASE 1.5: Leitura de Comentários (Oceano Azul)
        for sub in SUBREDDITS:
            print(f"\nBuscando comentários recentes no r/{sub}...")
            url = f"https://www.reddit.com/r/{sub}/comments.json?limit=100"
            try:
                response = requests.get(url, headers=headers, cookies=cookies_dict)
                if response.status_code != 200:
                    continue
                    
                dados = response.json()
                if 'data' in dados and 'children' in dados['data']:
                    for comment in dados['data']['children']:
                        info = comment['data']
                        autor = info.get('author', '')
                        # Comentários tem 'body' em vez de 'selftext' e não tem 'title'
                        texto = info.get('body', '')
                        titulo = "Comentário em Post"
                        permalink = info.get('permalink', '#')
                        created_utc = info.get('created_utc', 0)
                        
                        if autor == '[deleted]' or autor == 'AutoModerator':
                            continue
                            
                        # Limite de 30 dias
                        if time.time() - created_utc > 2592000:
                            continue
                            
                        conteudo_completo = texto.lower()
                        
                        # Blacklist
                        if any(bw in conteudo_completo for bw in BLACKLIST):
                            continue
                        
                        match_word = next((kw for kw in PALAVRAS_CHAVE.keys() if kw.lower() in conteudo_completo), None)
                        
                        if match_word:
                            if usuario_ja_contatado(conn, autor):
                                continue
                                
                            print(f"[?] Analisando intenção do COMENTÁRIO de u/{autor} com IA...")
                            if analisar_intencao_e_aprender(conn, titulo, texto, match_word):
                                match_category = PALAVRAS_CHAVE[match_word]
                                print(f"[!] ALVO (COMENTÁRIO) APROVADO: u/{autor}")
                                alvos_encontrados.append({
                                    'autor': autor,
                                    'titulo': titulo,
                                    'texto': texto,
                                    'assunto': f"Sobre o seu comentário no r/{sub}",
                                    'sub': sub,
                                    'match': match_word,
                                    'categoria': match_category,
                                    'permalink': permalink
                                })
                            else:
                                cursor.execute('SELECT word FROM negative_keywords')
                                BLACKLIST = [row[0].lower() for row in cursor.fetchall()]
            except Exception as e:
                pass
                
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
