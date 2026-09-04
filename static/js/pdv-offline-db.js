/**
 * PDV Offline Database & Sync Queue Manager (IndexedDB)
 * Suporte completo a multi-tenancy, fila transacional de vendas, controle de status,
 * idempotência por offline_uuid, cache local de catálogo e recuperação de falhas.
 */
class PDVOfflineDB {
    constructor() {
        this.dbName = 'PDVEnterpriseOfflineDB';
        this.version = 2;
        this.db = null;
    }

    async init() {
        if (this.db) return this.db;
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.version);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;

                // 1. Fila de Vendas Offline
                if (!db.objectStoreNames.contains('vendas_pendentes')) {
                    const storeVendas = db.createObjectStore('vendas_pendentes', { keyPath: 'offline_uuid' });
                    storeVendas.createIndex('empresa_id', 'empresa_id', { unique: false });
                    storeVendas.createIndex('status', 'status', { unique: false });
                    storeVendas.createIndex('data_hora_local', 'data_hora_local', { unique: false });
                }

                // 2. Cache de Produtos
                if (!db.objectStoreNames.contains('produtos_cache')) {
                    const storeProd = db.createObjectStore('produtos_cache', { keyPath: 'id' });
                    storeProd.createIndex('codigo_barras', 'codigo_barras', { unique: false });
                    storeProd.createIndex('sku', 'sku', { unique: false });
                    storeProd.createIndex('nome', 'nome', { unique: false });
                    storeProd.createIndex('empresa_id', 'empresa_id', { unique: false });
                }

                // 3. Cache de Clientes
                if (!db.objectStoreNames.contains('clientes_cache')) {
                    const storeCli = db.createObjectStore('clientes_cache', { keyPath: 'id' });
                    storeCli.createIndex('cpf_cnpj', 'cpf_cnpj', { unique: false });
                    storeCli.createIndex('nome', 'nome', { unique: false });
                    storeCli.createIndex('empresa_id', 'empresa_id', { unique: false });
                }

                // 4. Metadados e Configurações Locais
                if (!db.objectStoreNames.contains('config_local')) {
                    db.createObjectStore('config_local', { keyPath: 'chave' });
                }
            };

            request.onsuccess = (event) => {
                this.db = event.target.result;
                resolve(this.db);
            };

            request.onerror = (event) => {
                console.error('[IndexedDB] Erro ao abrir banco de dados local:', event.target.error);
                reject(event.target.error);
            };
        });
    }

    // =========================================================================
    // GESTÃO DA FILA DE VENDAS OFFLINE
    // =========================================================================

    /**
     * Salva uma venda na fila offline.
     * Garante que o offline_uuid e os metadados da operação estejam preenchidos.
     */
    async enfileirarVenda(vendaData) {
        if (!this.db) await this.init();
        return new Promise((resolve, reject) => {
            const registro = {
                offline_uuid: vendaData.offline_uuid || crypto.randomUUID(),
                empresa_id: vendaData.empresa_id || null,
                tipo_operacao: 'VENDA',
                payload: {
                    itens: vendaData.itens || [],
                    pagamentos: vendaData.pagamentos || [],
                    cliente_id: vendaData.cliente_id || null,
                    desconto: vendaData.desconto || 0.00,
                    observacao: vendaData.observacao || '',
                    sessao_caixa_id: vendaData.sessao_caixa_id || null,
                    total: vendaData.total || 0.00,
                },
                data_hora_local: vendaData.data_hora_local || new Date().toISOString(),
                status: 'PENDENTE', // PENDENTE, SINCRONIZANDO, SINCRONIZADA, ERRO_PERMANENTE, CONFLITO
                tentativas: 0,
                ultima_tentativa: null,
                mensagem_erro: null,
                data_hora_sincronizacao: null,
                resultado_servidor: null
            };

            const tx = this.db.transaction('vendas_pendentes', 'readwrite');
            const store = tx.objectStore('vendas_pendentes');
            const req = store.put(registro);

            req.onsuccess = () => resolve(registro);
            req.onerror = (e) => reject(e.target.error);
        });
    }

    /**
     * Retorna todas as vendas pendentes de sincronização para a empresa ativa.
     */
    async getVendasPendentes(empresa_id = null) {
        if (!this.db) await this.init();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('vendas_pendentes', 'readonly');
            const store = tx.objectStore('vendas_pendentes');
            const req = store.getAll();

            req.onsuccess = () => {
                let todas = req.result || [];
                if (empresa_id) {
                    todas = todas.filter(v => v.empresa_id === empresa_id);
                }
                const pendentes = todas.filter(v => v.status === 'PENDENTE' || v.status === 'SINCRONIZANDO');
                resolve(pendentes);
            };
            req.onerror = (e) => reject(e.target.error);
        });
    }

    /**
     * Retorna todas as vendas registradas localmente (pendentes, sincronizadas, com erro).
     */
    async getHistoricoFila(empresa_id = null) {
        if (!this.db) await this.init();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('vendas_pendentes', 'readonly');
            const store = tx.objectStore('vendas_pendentes');
            const req = store.getAll();

            req.onsuccess = () => {
                let todas = req.result || [];
                if (empresa_id) {
                    todas = todas.filter(v => v.empresa_id === empresa_id);
                }
                todas.sort((a, b) => new Date(b.data_hora_local) - new Date(a.data_hora_local));
                resolve(todas);
            };
            req.onerror = (e) => reject(e.target.error);
        });
    }

    /**
     * Atualiza o status e detalhes de uma venda após tentativa de envio.
     */
    async atualizarStatusVenda(offline_uuid, novoStatus, erro = null, resultadoServidor = null) {
        if (!this.db) await this.init();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('vendas_pendentes', 'readwrite');
            const store = tx.objectStore('vendas_pendentes');
            const getReq = store.get(offline_uuid);

            getReq.onsuccess = () => {
                const registro = getReq.result;
                if (!registro) {
                    return resolve(false);
                }

                registro.status = novoStatus;
                registro.tentativas = (registro.tentativas || 0) + 1;
                registro.ultima_tentativa = new Date().toISOString();
                registro.mensagem_erro = erro ? String(erro) : null;

                if (novoStatus === 'SINCRONIZADA') {
                    registro.data_hora_sincronizacao = new Date().toISOString();
                    registro.resultado_servidor = resultadoServidor;
                }

                const putReq = store.put(registro);
                putReq.onsuccess = () => resolve(registro);
                putReq.onerror = (e) => reject(e.target.error);
            };

            getReq.onerror = (e) => reject(e.target.error);
        });
    }

    /**
     * Remove uma venda da fila local.
     */
    async removerVenda(offline_uuid) {
        if (!this.db) await this.init();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('vendas_pendentes', 'readwrite');
            const store = tx.objectStore('vendas_pendentes');
            const req = store.delete(offline_uuid);

            req.onsuccess = () => resolve(true);
            req.onerror = (e) => reject(e.target.error);
        });
    }

    /**
     * Retorna estatísticas consolidadas da fila local.
     */
    async getEstatisticasFila(empresa_id = null) {
        const todas = await this.getHistoricoFila(empresa_id);
        return {
            total: todas.length,
            pendentes: todas.filter(v => v.status === 'PENDENTE' || v.status === 'SINCRONIZANDO').length,
            sincronizadas: todas.filter(v => v.status === 'SINCRONIZADA').length,
            erros: todas.filter(v => v.status === 'ERRO_PERMANENTE' || v.status === 'CONFLITO').length
        };
    }

    // =========================================================================
    // CACHE LOCAL DE PRODUTOS E CLIENTES
    // =========================================================================

    async salvarCatalogo(empresa_id, produtos = [], clientes = []) {
        if (!this.db) await this.init();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(['produtos_cache', 'clientes_cache', 'config_local'], 'readwrite');
            const storeProd = tx.objectStore('produtos_cache');
            const storeCli = tx.objectStore('clientes_cache');
            const storeCfg = tx.objectStore('config_local');

            produtos.forEach(p => {
                storeProd.put({ ...p, empresa_id });
            });

            clientes.forEach(c => {
                storeCli.put({ ...c, empresa_id });
            });

            storeCfg.put({
                chave: `ultima_sincronizacao_catalogo_${empresa_id}`,
                data_hora: new Date().toISOString(),
                total_produtos: produtos.length,
                total_clientes: clientes.length
            });

            tx.oncomplete = () => resolve(true);
            tx.onerror = (e) => reject(e.target.error);
        });
    }

    async buscarProdutoOffline(termo, empresa_id = null) {
        if (!this.db) await this.init();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('produtos_cache', 'readonly');
            const store = tx.objectStore('produtos_cache');
            const req = store.getAll();

            req.onsuccess = () => {
                let lista = req.result || [];
                if (empresa_id) {
                    lista = lista.filter(p => p.empresa_id === empresa_id);
                }
                const t = termo.toLowerCase().trim();
                const filtrados = lista.filter(p => 
                    (p.codigo_barras && p.codigo_barras.toLowerCase() === t) ||
                    (p.sku && p.sku.toLowerCase() === t) ||
                    (p.nome && p.nome.toLowerCase().includes(t))
                );
                resolve(filtrados);
            };
            req.onerror = (e) => reject(e.target.error);
        });
    }

    async buscarClienteOffline(termo, empresa_id = null) {
        if (!this.db) await this.init();
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('clientes_cache', 'readonly');
            const store = tx.objectStore('clientes_cache');
            const req = store.getAll();

            req.onsuccess = () => {
                let lista = req.result || [];
                if (empresa_id) {
                    lista = lista.filter(c => c.empresa_id === empresa_id);
                }
                const t = termo.toLowerCase().trim();
                const filtrados = lista.filter(c => 
                    (c.cpf_cnpj && c.cpf_cnpj.toLowerCase() === t) ||
                    (c.nome && c.nome.toLowerCase().includes(t)) ||
                    (c.telefone && c.telefone.includes(t))
                );
                resolve(filtrados);
            };
            req.onerror = (e) => reject(e.target.error);
        });
    }
}

// Instância global para uso no PDV
window.pdvOfflineDB = new PDVOfflineDB();
window.pdvOfflineDB.init().catch(err => console.warn('[IndexedDB] Inicialização em background:', err));
