import os
import sqlite3
import subprocess
import threading
import time
import requests
from dotenv import dotenv_values
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from functools import wraps

app = Flask(__name__)
app.secret_key = 'moritz_admin_super_secret_key'  # Necessário para usar sessões (Login)

# ==========================================
# SISTEMA DE LOGIN (SEGURANÇA)
# ==========================================
SENHA_ACESSO = "Meta10k@@"  # <--- A SENHA PARA ENTRAR NO PAINEL

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    erro = None
    if request.method == 'POST':
        if request.form.get('password') == SENHA_ACESSO:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            erro = "Senha incorreta. Acesso negado."
    return render_template('login.html', erro=erro)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))
# ==========================================

# Variáveis globais para controle de estado
bot_process = None
bot_logs = []
bot_status = "Pausado"

def run_bot():
    global bot_process, bot_status, bot_logs
    bot_status = "Trabalhando"
    bot_logs.append("[SISTEMA] Robô iniciado.")
    
    try:
        # Define variável de ambiente para forçar o Python a não "segurar" os prints
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        # Executa o bot.py e captura a saída
        import sys
        bot_process = subprocess.Popen(
            [sys.executable, "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env
        )
        
        proc = bot_process
        for line in iter(proc.stdout.readline, ''):
            if line:
                bot_logs.append(line.strip())
                # Mantém apenas as últimas 100 linhas para não pesar a memória
                if len(bot_logs) > 100:
                    bot_logs.pop(0)
                    
        proc.wait()
        
        # Se foi morto pelo usuário (código negativo no windows/linux), exibe mensagem amigável
        if proc.returncode != 0 and bot_status == "Pausado":
            bot_logs.append("[SISTEMA] Moritz foi colocado para dormir.")
        else:
            bot_logs.append(f"[SISTEMA] Processo finalizado (Código: {proc.returncode})")
    except Exception as e:
        bot_logs.append(f"[ERRO FATAL] {str(e)}")
    finally:
        bot_status = "Pausado"
        bot_process = None

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/status')
@login_required
def status():
    filter_type = request.args.get('filter', 'recentes')
    total_enviado = 0
    daily_count = 0
    recentes = []
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_database.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sent_messages")
            total_enviado = cursor.fetchone()[0]
            
            # Conta mensagens nas últimas 24h para medir a saúde da conta
            cursor.execute("SELECT COUNT(*) FROM sent_messages WHERE sent_at >= datetime('now', '-1 day')")
            daily_count = cursor.fetchone()[0]
            
            query_where = ""
            query_limit = ""
            if filter_type == 'hoje':
                query_where = "WHERE sent_at >= datetime('now', '-1 day')"
                query_limit = "LIMIT 50"
            elif filter_type == '7dias':
                query_where = "WHERE sent_at >= datetime('now', '-7 days')"
                query_limit = "LIMIT 100"
            elif filter_type == 'tudo':
                query_where = ""
                query_limit = "LIMIT 300"
            else: # recentes
                query_where = ""
                query_limit = "LIMIT 10"

            # Tenta pegar as colunas novas, se der erro (banco antigo sem colunas), pega só o básico
            try:
                # Modificado: formatando data no SQL
                cursor.execute(f"SELECT username, subreddit, keyword, strftime('%d/%m/%Y às %H:%M', datetime(sent_at, 'localtime')), post_title, message, permalink FROM sent_messages {query_where} ORDER BY sent_at DESC {query_limit}")
                recentes = [{"username": row[0], "subreddit": row[1], "keyword": row[2], "date": row[3], "title": row[4], "message": row[5], "permalink": row[6]} for row in cursor.fetchall()]
            except:
                try:
                    # Banco intermediário (sem permalink)
                    cursor.execute(f"SELECT username, subreddit, keyword, strftime('%d/%m/%Y às %H:%M', datetime(sent_at, 'localtime')), post_title, message FROM sent_messages {query_where} ORDER BY sent_at DESC {query_limit}")
                    recentes = [{"username": row[0], "subreddit": row[1], "keyword": row[2], "date": row[3], "title": row[4], "message": row[5], "permalink": "#"} for row in cursor.fetchall()]
                except:
                    # Banco muito antigo
                    cursor.execute(f"SELECT username, sent_at FROM sent_messages {query_where} ORDER BY sent_at DESC {query_limit}")
                    recentes = [{"username": row[0], "subreddit": "Desconhecido", "keyword": "N/A", "date": row[1], "title": "Indisponível", "message": "Indisponível", "permalink": "#"} for row in cursor.fetchall()]
                
            conn.close()
        except:
            pass
            
    # Subreddits lidos do bot.py poderiam ser dinâmicos, mas vamos focar em mostrar as listas recentes
    subreddits_monitorados = 5 
    
    return jsonify({
        "status": bot_status,
        "total_enviado": total_enviado,
        "daily_count": daily_count,
        "subreddits": subreddits_monitorados,
        "logs": bot_logs[-50:],
        "recentes": recentes
    })

@app.route('/api/start', methods=['POST'])
@login_required
def start_bot():
    global bot_process
    if bot_process is None:
        thread = threading.Thread(target=run_bot)
        thread.daemon = True
        thread.start()
        return jsonify({"success": True, "message": "Robô iniciado com sucesso."})
    return jsonify({"success": False, "message": "Robô já está rodando."})

@app.route('/api/stop', methods=['POST'])
@login_required
def stop_bot():
    global bot_process, bot_status
    if bot_process:
        bot_process.terminate()
        bot_status = "Pausado"
        bot_logs.append("💤 [SISTEMA] Robô parado pelo usuário. Moritz entrou em descanso.")
    return jsonify({"status": "success", "message": "Bot parado"})

@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_database.db")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Garante que as tabelas existem
        cursor.execute('CREATE TABLE IF NOT EXISTS keywords (word TEXT PRIMARY KEY, category TEXT DEFAULT "creator")')
        cursor.execute('CREATE TABLE IF NOT EXISTS subreddits (name TEXT PRIMARY KEY)')
        
        # Migração: adiciona coluna category se não existir
        colunas_kw = [row[1] for row in cursor.execute("PRAGMA table_info(keywords)").fetchall()]
        if 'category' not in colunas_kw:
            cursor.execute("ALTER TABLE keywords ADD COLUMN category TEXT DEFAULT 'creator'")
        
        # Popula padrões se vazio
        cursor.execute('SELECT COUNT(*) FROM keywords')
        if cursor.fetchone()[0] == 0:
            default_kws = ["preciso trabalhar", "trabalho online", "renda extra", "ganhar dinheiro na internet", "sou freelancer", "dificuldade freelancer", "calote freelancer", "editor de vídeo", "design gráfico", "gestor de tráfego", "contratar freelancer", "preciso de editor de vídeo", "procurar designer", "agência de marketing", "dificuldade em", "problema com"]
            cursor.executemany('INSERT INTO keywords (word, category) VALUES (?, "creator")', [(kw,) for kw in default_kws])
            
        cursor.execute('SELECT COUNT(*) FROM subreddits')
        if cursor.fetchone()[0] == 0:
            default_subs = ["freelance", "SideHustle", "VagasArrombadas", "brdev", "empreendedorismo", "all"]
            cursor.executemany('INSERT INTO subreddits (name) VALUES (?)', [(s,) for s in default_subs])
            
        conn.commit()

        cursor.execute("SELECT word, category FROM keywords")
        keywords = [{"word": row[0], "category": row[1]} for row in cursor.fetchall()]
        cursor.execute("SELECT name FROM subreddits")
        subreddits = [row[0] for row in cursor.fetchall()]
        conn.close()
        return jsonify({"keywords": keywords, "subreddits": subreddits})
    except Exception as e:
        print("Erro get_config:", e)
        return jsonify({"keywords": [], "subreddits": []})

@app.route('/api/config', methods=['POST'])
@login_required
def add_config():
    data = request.json
    item_type = data.get('type') # 'keyword' or 'subreddit'
    value = data.get('value')
    category = data.get('category', 'creator')
    if not value: return jsonify({"success": False})
    
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_database.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        if item_type == 'keyword':
            cursor.execute("INSERT OR REPLACE INTO keywords (word, category) VALUES (?, ?)", (value, category))
        else:
            cursor.execute("INSERT OR REPLACE INTO subreddits (name) VALUES (?)", (value,))
        conn.commit()
    except Exception as e:
        print("Erro ao adicionar config:", e)
    conn.close()
    return jsonify({"success": True})

@app.route('/api/config', methods=['DELETE'])
@login_required
def del_config():
    data = request.json
    item_type = data.get('type')
    value = data.get('value')
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_database.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    if item_type == 'keyword':
        cursor.execute("DELETE FROM keywords WHERE word=?", (value,))
    else:
        cursor.execute("DELETE FROM subreddits WHERE name=?", (value,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/agent-config', methods=['GET'])
@login_required
def get_agent_config():
    env_vars = dotenv_values(".env")
    openrouter_key = env_vars.get("OPENROUTER_API_KEY")
    gemini_key = env_vars.get("GEMINI_API_KEY")
    
    active_api = "Nenhuma"
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_database.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_state WHERE key='active_api'")
            res = cursor.fetchone()
            if res:
                active_api = res[0]
            conn.close()
        except Exception as e:
            pass
            
    apis = []
    
    # OpenRouter API
    if openrouter_key:
        try:
            resp = requests.get("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": f"Bearer {openrouter_key}"}, timeout=5)
            if resp.status_code == 200:
                data = resp.json().get('data', {})
                limit = data.get('limit')
                usage = data.get('usage', 0)
                limit_text = "Ilimitado" if limit is None else f"${limit}"
                restante_text = "Ilimitado" if limit is None else f"${limit - usage:.4f}"
                pct = 0 if limit is None else min((usage / limit) * 100, 100)
                
                apis.append({
                    "name": "OpenRouter",
                    "status": "Ativo" if active_api == "OpenRouter" else "Em Espera (Fallback)",
                    "is_active": active_api == "OpenRouter",
                    "key_masked": f"{openrouter_key[:8]}...{openrouter_key[-4:]}",
                    "usage": f"${usage:.4f}",
                    "limit": limit_text,
                    "remaining": restante_text,
                    "percentage": pct
                })
        except Exception as e:
            print("Erro openrouter API:", e)
            pass

    # Gemini API
    if gemini_key:
        apis.append({
            "name": "Google Gemini (Nativo)",
            "status": "Ativo" if active_api == "Gemini" else "Em Espera (Fallback)",
            "is_active": active_api == "Gemini",
            "key_masked": f"{gemini_key[:8]}...{gemini_key[-4:]}",
            "usage": "Cota Gerenciada pelo Google",
            "limit": "-",
            "remaining": "-",
            "percentage": 0
        })

    if not apis:
        apis.append({"name": "Nenhuma API Configurada", "status": "Inativo", "is_active": False, "key_masked": "-", "usage": "-", "limit": "-", "remaining": "-", "percentage": 0})
        
    return jsonify({"apis": apis})

if __name__ == '__main__':
    # Para desenvolvimento
    app.run(host='0.0.0.0', port=5000, debug=True)
