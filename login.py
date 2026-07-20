import browser_cookie3
import json

def extrair_cookies_do_chrome():
    print("Iniciando extração mágica de cookies do seu Google Chrome...")
    try:
        # Pega os cookies diretamente do navegador Chrome real do usuário
        cj = browser_cookie3.chrome(domain_name='.reddit.com')
        
        cookies_formatados = []
        for c in cj:
            cookies_formatados.append({
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "expires": c.expires if c.expires else -1,
                "httpOnly": c.has_nonstandard_attr('HttpOnly'),
                "secure": c.secure,
                "sameSite": "Lax"
            })
            
        if len(cookies_formatados) == 0:
            print("ERRO: Nenhum cookie do Reddit encontrado no seu Chrome.")
            print("Você tem certeza que está logado no Reddit no seu Google Chrome principal?")
            return

        estado = {
            "cookies": cookies_formatados,
            "origins": []
        }
        
        with open("state.json", "w") as f:
            json.dump(estado, f, indent=4)
            
        print(f"SUCESSO! {len(cookies_formatados)} cookies copiados direto do seu Chrome.")
        print("Arquivo 'state.json' criado com sucesso. Passamos pela barreira de segurança!")
        
    except Exception as e:
        print(f"Ocorreu um erro ao extrair os cookies: {e}")
        print("Tente fechar o Google Chrome completamente e rodar o script novamente.")

if __name__ == "__main__":
    extrair_cookies_do_chrome()
