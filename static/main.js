let pollInterval;
const consoleOutput = document.getElementById('console-output');
const statusText = document.getElementById('status-text');
const statusIndicator = document.getElementById('status-indicator');
const totalEnviado = document.getElementById('total-enviado');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const mascot = document.getElementById('robot-mascot');

let currentFilter = 'recentes';
let currentKeywordTab = 'creator';

function switchKeywordTab(tabName) {
    currentKeywordTab = tabName;
    const tabCreator = document.getElementById('tab-creator');
    const tabEmpresa = document.getElementById('tab-empresa');
    
    if (tabName === 'creator') {
        tabCreator.style.background = 'var(--accent-color)';
        tabCreator.style.color = '#000';
        tabCreator.style.border = 'none';
        
        tabEmpresa.style.background = 'transparent';
        tabEmpresa.style.color = 'var(--text-secondary)';
        tabEmpresa.style.border = '1px solid var(--glass-border)';
    } else {
        tabEmpresa.style.background = 'var(--accent-color)';
        tabEmpresa.style.color = '#000';
        tabEmpresa.style.border = 'none';
        
        tabCreator.style.background = 'transparent';
        tabCreator.style.color = 'var(--text-secondary)';
        tabCreator.style.border = '1px solid var(--glass-border)';
    }
    loadConfig();
}

// Lógica dos Botões de Filtro de Data
document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        // Remove a classe active de todos
        document.querySelectorAll('.filter-btn').forEach(b => {
            b.classList.remove('active');
            b.style.background = 'transparent';
            b.style.color = 'var(--text-secondary)';
        });
        
        // Adiciona classe active no botão clicado
        const target = e.target;
        target.classList.add('active');
        target.style.background = 'var(--glass-highlight)';
        target.style.color = '#fff';
        
        currentFilter = target.getAttribute('data-filter');
        fetchStatus(); // Busca instantaneamente com o novo filtro
    });
});

function setMascotState(isWorking) {
    if (isWorking) {
        mascot.setAttribute("class", "working");
    } else {
        mascot.setAttribute("class", "paused");
    }
}

function updateConsole(logs) {
    // Verifica se o usuário está no final da barra de rolagem
    const isScrolledToBottom = consoleOutput.scrollHeight - consoleOutput.clientHeight <= consoleOutput.scrollTop + 10;
    const currentScrollTop = consoleOutput.scrollTop;
    
    // Só atualiza a tela se tiver log novo (evita piscar a tela e perder a posição de leitura)
    const newLogsStr = JSON.stringify(logs);
    if (consoleOutput.dataset.lastLogs === newLogsStr) return;
    consoleOutput.dataset.lastLogs = newLogsStr;

    consoleOutput.innerHTML = '';
    logs.forEach(line => {
        const div = document.createElement('div');
        div.className = 'console-line';
        
        // Estilizar a linha baseado no conteúdo
        if (line.includes('[ERRO]')) {
            div.classList.add('error');
            div.style.color = '#f87171'; // Vermelho
        } else if (line.includes('[SUCESSO]') || line.includes('[!] ALVO ENCONTRADO')) {
            div.classList.add('success');
            div.style.color = '#a3e635'; // Verde
        } else if (line.includes('[SISTEMA]')) {
            div.classList.add('system');
            div.style.color = '#fbbf24'; // Amarelo
        } else {
            div.style.color = '#e2e8f0'; // Branco/Cinza padrão
        }
        
        div.textContent = line;
        consoleOutput.appendChild(div);
    });
    
    // Rola para o final automaticamente SOMENTE se o usuário já estava no final
    if (isScrolledToBottom) {
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
    } else {
        consoleOutput.scrollTop = currentScrollTop; // Mantém onde ele estava lendo
    }
}

function fetchStatus() {
    fetch(`/api/status?filter=${currentFilter}`)
        .then(response => response.json())
        .then(data => {
            // Atualiza botões
            if (data.status === "Trabalhando") {
                btnStart.disabled = true;
                btnStop.disabled = false;
                statusIndicator.className = 'status-indicator working';
                
                // Se estava pausado antes, muda a animação
                if (statusText.textContent !== "Trabalhando") {
                    setMascotState(true);
                }
            } else {
                btnStart.disabled = false;
                btnStop.disabled = true;
                statusIndicator.className = 'status-indicator paused';
                
                if (statusText.textContent !== "Pausado") {
                    setMascotState(false);
                }
            }
            
            statusText.textContent = data.status;
            totalEnviado.textContent = data.total_enviado;
            
            // Lógica de Saúde da Conta
            const daily = data.daily_count || 0;
            const limit = 30; // Limite seguro sugerido por dia
            const healthBar = document.getElementById('health-bar');
            const healthText = document.getElementById('daily-count-text');
            const healthStatus = document.getElementById('health-status-text');
            const healthIcon = document.getElementById('health-icon');
            
            healthText.textContent = `${daily} / ${limit}`;
            
            let percent = (daily / limit) * 100;
            if (percent > 100) percent = 100;
            healthBar.style.width = `${percent}%`;
            
            if (daily < 15) {
                healthBar.style.background = 'var(--success-color)';
                healthStatus.textContent = 'Seguro e Estável';
                healthStatus.style.color = 'var(--success-color)';
                healthIcon.setAttribute('stroke', 'var(--success-color)');
            } else if (daily < 25) {
                healthBar.style.background = '#f59e0b'; // Laranja/Atenção
                healthStatus.textContent = 'Atenção: Moderado';
                healthStatus.style.color = '#f59e0b';
                healthIcon.setAttribute('stroke', '#f59e0b');
            } else {
                healthBar.style.background = 'var(--danger-color)';
                healthStatus.textContent = 'Risco Alto - Pause o Bot';
                healthStatus.style.color = 'var(--danger-color)';
                healthIcon.setAttribute('stroke', 'var(--danger-color)');
            }
            
            updateConsole(data.logs);
            
            // Atualiza a tabela de recentes
            const tbody = document.getElementById('recent-targets-body');
            tbody.innerHTML = '';
            
            // Variável global para armazenar os dados recentes para o modal
            window.recentTargetsData = data.recentes;

            if (data.recentes && data.recentes.length > 0) {
                data.recentes.forEach((row, index) => {
                    const tr = document.createElement('tr');
                    tr.style.borderBottom = "1px solid rgba(255,255,255,0.05)";
                    
                    let subHtml = `r/${row.subreddit}`;
                    if(row.permalink && row.permalink !== '#') {
                        subHtml = `<a href="https://www.reddit.com${row.permalink}" target="_blank" style="color: #60a5fa; text-decoration: none; display: flex; align-items: center; gap: 0.25rem;">
                                    r/${row.subreddit} <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                                   </a>`;
                    }
                    
                    tr.innerHTML = `
                        <td style="padding: 0.75rem; color: #a7f3d0; font-weight: 600;">u/${row.username}</td>
                        <td style="padding: 0.75rem;">${subHtml}</td>
                        <td style="padding: 0.75rem; color: var(--accent-color);">"${row.keyword}"</td>
                        <td style="padding: 0.75rem; color: var(--text-secondary); font-size: 0.85rem;">${row.date}</td>
                        <td style="padding: 0.75rem; text-align: center;">
                            <button onclick="openDetailsModal(${index})" style="background: var(--glass-highlight); border: 1px solid var(--accent-color); color: #fff; padding: 0.3rem 0.8rem; border-radius: 0.25rem; cursor: pointer; transition: all 0.2s;">Ver</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            } else {
                tbody.innerHTML = '<tr><td colspan="5" style="padding: 1rem; text-align: center; color: var(--text-secondary);">Nenhum alvo encontrado ainda.</td></tr>';
            }
        })
        .catch(err => console.error("Erro ao buscar status:", err));
}

function openDetailsModal(index) {
    const data = window.recentTargetsData[index];
    if(data) {
        document.getElementById('modal-user').textContent = 'u/' + data.username;
        
        let titleHtml = data.title || 'Indisponível';
        if(data.permalink && data.permalink !== '#') {
            titleHtml += ` <br><a href="https://www.reddit.com${data.permalink}" target="_blank" style="color: #60a5fa; font-size: 0.85rem; text-decoration: underline; margin-top: 0.5rem; display: inline-block;">Ver Postagem Original no Reddit</a>`;
        }
        document.getElementById('modal-title').innerHTML = titleHtml;
        
        document.getElementById('modal-message').textContent = data.message || 'Indisponível';
        document.getElementById('details-modal').style.display = 'flex';
    }
}

btnStart.addEventListener('click', () => {
    fetch('/api/start', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            if(data.success) {
                fetchStatus(); // Atualiza imediatamente
            }
        });
});

btnStop.addEventListener('click', () => {
    fetch('/api/stop', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            console.log(data);
            fetchStatus(); // Força uma atualização imediata para mostrar Pausado
        });
});

// Configurações e Alvos (Palavras e Subs)
function openConfigModal() {
    document.getElementById('config-modal').style.display = 'flex';
    loadConfig();
}

function loadConfig() {
    fetch('/api/config')
        .then(res => res.json())
        .then(data => {
            const kwList = document.getElementById('keywords-list');
            const subList = document.getElementById('subreddits-list');
            
            kwList.style.display = 'flex';
            kwList.style.flexWrap = 'wrap';
            kwList.style.gap = '0.5rem';
            kwList.style.alignContent = 'flex-start';

            subList.style.display = 'flex';
            subList.style.flexWrap = 'wrap';
            subList.style.gap = '0.5rem';
            subList.style.alignContent = 'flex-start';

            kwList.innerHTML = '';
            subList.innerHTML = '';
            
            // Filtra as palavras-chave pela aba atual
            const filteredKeywords = data.keywords.filter(kwObj => (kwObj.category || 'creator') === currentKeywordTab);
            
            filteredKeywords.forEach(kwObj => {
                const kw = kwObj.word;
                kwList.innerHTML += `<div style="background: rgba(163, 230, 53, 0.1); border: 1px solid rgba(163, 230, 53, 0.3); color: #a3e635; padding: 0.2rem 0.6rem; border-radius: 1rem; font-size: 0.85rem; display: flex; align-items: center; gap: 0.5rem;">
                    <span>${kw}</span>
                    <button onclick="delConfig('keyword', '${kw}')" style="background: none; border: none; color: var(--danger-color); cursor: pointer; font-size: 0.8rem; padding: 0;">&times;</button>
                </div>`;
            });
            
            data.subreddits.forEach(sub => {
                subList.innerHTML += `<div style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); color: #fff; padding: 0.2rem 0.6rem; border-radius: 1rem; font-size: 0.85rem; display: flex; align-items: center; gap: 0.5rem;">
                    <span>r/${sub}</span>
                    <button onclick="delConfig('subreddit', '${sub}')" style="background: none; border: none; color: var(--danger-color); cursor: pointer; font-size: 0.8rem; padding: 0;">&times;</button>
                </div>`;
            });
        });
}

function addConfig(type) {
    const input = document.getElementById(`new-${type}`);
    const val = input.value.trim();
    if(!val) return;
    
    fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            type: type, 
            value: val,
            category: type === 'keyword' ? currentKeywordTab : 'creator'
        })
    }).then(() => {
        input.value = '';
        loadConfig();
    });
}

function delConfig(type, val) {
    fetch('/api/config', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: type, value: val })
    }).then(() => loadConfig());
}

// Inicia com o mascote parado
setMascotState(false);

// Busca status a cada 2 segundos
pollInterval = setInterval(fetchStatus, 2000);
fetchStatus();

// Modal de Configuração do Agente (APIs)
function openAgentConfigModal() {
    document.getElementById('agent-config-modal').style.display = 'flex';
    const container = document.getElementById('apis-list-container');
    container.innerHTML = '<div style="text-align: center; color: var(--text-secondary); padding: 2rem;">Carregando dados das APIs...</div>';
    
    fetch('/api/agent-config')
        .then(res => res.json())
        .then(data => {
            container.innerHTML = '';
            if(data.apis && data.apis.length > 0) {
                data.apis.forEach(api => {
                    const statusColor = api.is_active ? 'var(--success-color)' : 'var(--text-secondary)';
                    const badgeText = api.is_active ? '🟢 [EM USO] ' + api.status : '⚪ ' + api.status;
                    
                    container.innerHTML += `
                        <div style="background: rgba(0,0,0,0.4); border: 1px solid ${api.is_active ? 'var(--success-color)' : 'var(--glass-border)'}; border-radius: 0.5rem; padding: 1rem; position: relative;">
                            ${api.is_active ? '<div style="position: absolute; top: 0; left: 0; width: 4px; height: 100%; background: var(--success-color); border-radius: 0.5rem 0 0 0.5rem;"></div>' : ''}
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; padding-left: 0.5rem;">
                                <h4 style="color: #fff; margin: 0; display: flex; align-items: center; gap: 0.5rem;">
                                    ${api.name}
                                    <span style="font-size: 0.7rem; background: ${statusColor}40; color: ${statusColor}; padding: 0.2rem 0.6rem; border-radius: 1rem; border: 1px solid ${statusColor}; font-weight: bold; letter-spacing: 0.5px;">${badgeText}</span>
                                </h4>
                            </div>
                            
                            <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem;">
                                <strong>Chave:</strong> <span style="font-family: monospace;">${api.key_masked}</span>
                            </div>
                            
                            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #e2e8f0; margin-bottom: 0.5rem;">
                                <span>Consumido: <strong>${api.usage}</strong></span>
                                <span>Restante: <strong>${api.remaining}</strong> (Limite: ${api.limit})</span>
                            </div>
                            
                            <div style="width: 100%; height: 8px; background: rgba(0,0,0,0.5); border-radius: 4px; overflow: hidden;">
                                <div style="height: 100%; width: ${api.percentage}%; background: ${api.percentage > 90 ? 'var(--danger-color)' : api.percentage > 70 ? '#f59e0b' : 'var(--accent-color)'}; transition: width 0.5s;"></div>
                            </div>
                        </div>
                    `;
                });
            } else {
                container.innerHTML = '<div style="text-align: center; color: var(--text-secondary); padding: 2rem;">Nenhuma API encontrada.</div>';
            }
        })
        .catch(err => {
            container.innerHTML = '<div style="text-align: center; color: var(--danger-color); padding: 2rem;">Erro ao carregar os dados.</div>';
        });
}
