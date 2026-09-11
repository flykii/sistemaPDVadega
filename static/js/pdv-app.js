/**
 * PDV App Enterprise - Núcleo de Operação de Frente de Caixa & PWA Sync
 * Suporta:
 * - Persistência ininterrupta do carrinho local (localStorage / estado de sessão)
 * - Operação online e offline transparente com IndexedDB
 * - Idempotência estrita por offline_uuid (reutilizado em todos os retries)
 * - Monitoramento contínuo de conectividade real via Heartbeat /api/v1/pdv/ping/
 * - Cache local de produtos/clientes para consulta rápida e bipe de código de barras
 * - Sincronização automática em lote quando reconectar
 * - Suporte a múltiplos pagamentos reais (Dinheiro, PIX, Débito, Crédito, Crediário), descontos R$/% e validação de crédito no crediário.
 * - Pausa de vendas com nome persistente e retenção de estado ao retomar.
 */

function roundMoney(val) {
    const num = typeof val === 'number' ? val : parseFloat(String(val).replace(',', '.'));
    if (isNaN(num)) return 0.00;
    return Math.round((num + Number.EPSILON) * 100) / 100;
}

class PDVApp {
    constructor() {
        this.cart = [];
        this.payments = [];
        this.selectedCustomer = null;
        this.discountType = 'BRL'; // 'BRL' ou 'PERCENT'
        this.discountValue = 0.00;
        this.currentSaleName = '';
        this.isOnline = navigator.onLine;
        this.isSyncing = false;
        this.isProcessingSale = false;
        this.pausedSales = JSON.parse(localStorage.getItem('pdv_paused_sales') || '[]');
        this.selectedPaymentMethod = 'DINHEIRO';
        this.pingInterval = null;
        this.shortcuts = {
            FINALIZAR_COMPRA: 'F5',
            FOCAR_BUSCA: 'F2',
            IDENTIFICAR_CLIENTE: 'F4',
            CANCELAR_FECHAR: 'Escape'
        };

        this.init();
    }

    init() {
        this.initShortcuts();
        this.bindEvents();
        this.carregarCarrinhoPersistido();
        this.startHeartbeat();
        this.updateNetworkBadge();
        this.renderCart();
        this.updatePausedBadge();
        this.carregarCatalogoOffline();
    }

    initShortcuts() {
        const defaults = {
            FINALIZAR_COMPRA: 'F5',
            FOCAR_BUSCA: 'F2',
            IDENTIFICAR_CLIENTE: 'F4',
            CANCELAR_FECHAR: 'Escape',
            PAG_DINHEIRO: 'F6',
            PAG_PIX: 'F7',
            PAG_DEBITO: 'F8',
            PAG_CREDITO: 'F9'
        };

        if (window.PDV_SHORTCUTS && typeof window.PDV_SHORTCUTS === 'object' && Object.keys(window.PDV_SHORTCUTS).length > 0) {
            this.shortcuts = { ...defaults, ...window.PDV_SHORTCUTS };
            try {
                localStorage.setItem('pdv_shortcuts_config', JSON.stringify(this.shortcuts));
            } catch(e) {
                console.warn('Erro ao salvar atalhos no localStorage:', e);
            }
        } else {
            try {
                const cached = localStorage.getItem('pdv_shortcuts_config');
                if (cached) {
                    this.shortcuts = { ...defaults, ...JSON.parse(cached) };
                } else {
                    this.shortcuts = defaults;
                }
            } catch(e) {
                this.shortcuts = defaults;
            }
        }
        this.atualizarLabelsAtalhosUI();
    }

    atualizarLabelsAtalhosUI() {
        const getLabel = (tecla) => (tecla === 'Escape' ? 'ESC' : tecla);

        const btnFin = document.getElementById('label-shortcut-finalizar');
        if (btnFin) btnFin.textContent = getLabel(this.shortcuts.FINALIZAR_COMPRA);

        const btnModFin = document.getElementById('label-shortcut-modal-finalizar');
        if (btnModFin) btnModFin.textContent = getLabel(this.shortcuts.FINALIZAR_COMPRA);

        const kbdFin = document.getElementById('kbd-shortcut-finalizar');
        if (kbdFin) kbdFin.textContent = getLabel(this.shortcuts.FINALIZAR_COMPRA);

        const lblBusca = document.getElementById('label-shortcut-busca');
        if (lblBusca) lblBusca.textContent = getLabel(this.shortcuts.FOCAR_BUSCA);

        const kbdBusca = document.getElementById('kbd-shortcut-busca');
        if (kbdBusca) kbdBusca.textContent = getLabel(this.shortcuts.FOCAR_BUSCA);

        const lblCli = document.getElementById('label-shortcut-cliente');
        if (lblCli) lblCli.textContent = getLabel(this.shortcuts.IDENTIFICAR_CLIENTE);

        const kbdCli = document.getElementById('kbd-shortcut-cliente');
        if (kbdCli) kbdCli.textContent = getLabel(this.shortcuts.IDENTIFICAR_CLIENTE);

        const kbdFechar = document.getElementById('kbd-shortcut-fechar');
        if (kbdFechar) kbdFechar.textContent = getLabel(this.shortcuts.CANCELAR_FECHAR);
    }

    bindEvents() {
        const isPdvPage = document.body && (document.body.dataset.page === 'pdv' || !!document.querySelector('.pdv-container'));

        // Registra atalhos de teclado EXCLUSIVAMENTE quando estiver no contexto do PDV
        if (isPdvPage) {
            document.addEventListener('keydown', (e) => {
                const paymentModalEl = document.getElementById('paymentModal');
                const isPaymentModalOpen = paymentModalEl && paymentModalEl.classList.contains('show');
                const confirmModalEl = document.getElementById('confirmSaleModal');
                const isConfirmModalOpen = confirmModalEl && confirmModalEl.classList.contains('show');

                const isKeyMatch = (funcCode) => {
                    const configured = this.shortcuts ? this.shortcuts[funcCode] : null;
                    if (!configured) return false;
                    const normConfigured = configured.toUpperCase();
                    const normEventKey = e.key.toUpperCase();
                    if ((normConfigured === 'ESC' || normConfigured === 'ESCAPE') && normEventKey === 'ESCAPE') return true;
                    return normEventKey === normConfigured;
                };

                if (isKeyMatch('FOCAR_BUSCA')) {
                    e.preventDefault();
                    this.focusBarcodeScanner();
                } else if (isKeyMatch('IDENTIFICAR_CLIENTE')) {
                    e.preventDefault();
                    const debtItem = this.cart.find(i => i.tipo_item === 'RECEBIMENTO_DIVIDA');
                    if (debtItem) {
                        alert(`Este checkout possui um recebimento de dívida de ${debtItem.cliente_nome}. O cliente do checkout deve ser o mesmo cliente da dívida.`);
                        return;
                    }
                    const cliSelect = document.getElementById('cliente-select') || document.getElementById('modal-cliente-select');
                    if (cliSelect) cliSelect.focus();
                } else if (isKeyMatch('FINALIZAR_COMPRA')) {
                    e.preventDefault();
                    if (isConfirmModalOpen) {
                        this.confirmarEGravarVenda();
                    } else if (isPaymentModalOpen) {
                        this.abrirModalConfirmacao();
                    } else {
                        this.abrirModalPagamento();
                    }
                } else if (isKeyMatch('CANCELAR_FECHAR')) {
                    if (isConfirmModalOpen) {
                        e.preventDefault();
                        this.cancelarConfirmacaoVenda();
                    } else {
                        this.closeModals();
                    }
                } else if (isKeyMatch('PAG_DINHEIRO')) {
                    e.preventDefault();
                    if (!isPaymentModalOpen && !isConfirmModalOpen) this.abrirModalPagamento();
                    this.selecionarFormaPagamento('DINHEIRO');
                } else if (isKeyMatch('PAG_PIX')) {
                    e.preventDefault();
                    if (!isPaymentModalOpen && !isConfirmModalOpen) this.abrirModalPagamento();
                    this.selecionarFormaPagamento('PIX');
                } else if (isKeyMatch('PAG_DEBITO')) {
                    e.preventDefault();
                    if (!isPaymentModalOpen && !isConfirmModalOpen) this.abrirModalPagamento();
                    this.selecionarFormaPagamento('CARTAO_DEBITO');
                } else if (isKeyMatch('PAG_CREDITO')) {
                    e.preventDefault();
                    if (!isPaymentModalOpen && !isConfirmModalOpen) this.abrirModalPagamento();
                    this.selecionarFormaPagamento('CARTAO_CREDITO');
                } else if (e.key === 'Enter') {
                    if (isConfirmModalOpen) {
                        e.preventDefault();
                        this.confirmarEGravarVenda();
                    } else if (isPaymentModalOpen) {
                        const activeEl = document.activeElement;
                        if (activeEl && (activeEl.id === 'modal-pay-valor' || activeEl.id === 'modal-cliente-select')) {
                            e.preventDefault();
                            this.adicionarParcelaPagamento();
                        }
                    }
                }
            });
        }

        const payModalEl = document.getElementById('paymentModal');
        if (payModalEl) {
            payModalEl.addEventListener('shown.bs.modal', () => {
                const valorInput = document.getElementById('modal-pay-valor');
                if (valorInput) {
                    valorInput.focus();
                    valorInput.select();
                }
            });
            payModalEl.addEventListener('hidden.bs.modal', () => {
                if (!this.isTransitioningToConfirm) {
                    this.resetModalPagamento();
                }
            });
        }

        const confirmModalEl = document.getElementById('confirmSaleModal');
        if (confirmModalEl) {
            confirmModalEl.addEventListener('hidden.bs.modal', () => {
                if (!this.isTransitioningToPayment && !this.isProcessingSale) {
                    this.resetModalPagamento();
                }
            });
        }

        const cliSelect = document.getElementById('cliente-select');
        if (cliSelect) {
            cliSelect.addEventListener('change', () => {
                this.salvarCarrinhoPersistido();
            });
        }

        window.addEventListener('online', () => {
            this.checkBackendConnectivity();
        });

        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.updateNetworkBadge();
        });
    }

    startHeartbeat() {
        this.checkBackendConnectivity();
        if (this.pingInterval) clearInterval(this.pingInterval);
        this.pingInterval = setInterval(() => {
            this.checkBackendConnectivity();
        }, 10000);
    }

    async checkBackendConnectivity() {
        if (!navigator.onLine) {
            this.isOnline = false;
            this.updateNetworkBadge();
            return;
        }

        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 4000);
            const resp = await fetch('/api/v1/pdv/ping/', { credentials: 'same-origin', signal: controller.signal });
            clearTimeout(timeoutId);

            if (resp.ok) {
                const wasOffline = !this.isOnline;
                this.isOnline = true;
                this.updateNetworkBadge();
                if (wasOffline) {
                    this.sincronizarVendasOffline();
                }
            } else {
                this.isOnline = false;
                this.updateNetworkBadge();
            }
        } catch (e) {
            this.isOnline = false;
            this.updateNetworkBadge();
        }
    }

    async updateNetworkBadge() {
        const badge = document.getElementById('network-status-badge');
        const syncBadge = document.getElementById('sync-status-badge');
        if (!badge) return;

        let pendentesCount = 0;
        if (window.pdvOfflineDB) {
            const stats = await window.pdvOfflineDB.getEstatisticasFila();
            pendentesCount = stats.pendentes;
        }

        if (this.isSyncing) {
            badge.className = 'badge bg-info text-dark ms-2';
            badge.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> SINCRONIZANDO...';
        } else if (this.isOnline) {
            if (pendentesCount > 0) {
                badge.className = 'badge bg-warning text-dark ms-2';
                badge.innerHTML = `<i class="bi bi-cloud-arrow-up-fill me-1"></i> ONLINE (${pendentesCount} pendente(s))`;
            } else {
                badge.className = 'badge bg-success ms-2';
                badge.innerHTML = '<i class="bi bi-wifi me-1"></i> ONLINE';
            }
        } else {
            badge.className = 'badge bg-secondary text-white ms-2';
            badge.innerHTML = `<i class="bi bi-wifi-off me-1"></i> OFFLINE (${pendentesCount} pendente(s))`;
        }

        if (syncBadge) {
            syncBadge.innerText = pendentesCount;
            syncBadge.style.display = pendentesCount > 0 ? 'inline-block' : 'none';
        }
    }

    async carregarCatalogoOffline() {
        if (!navigator.onLine || !window.pdvOfflineDB) return;
        try {
            const resp = await fetch('/api/v1/pdv/produtos-offline/', { credentials: 'same-origin' });
            if (resp.ok) {
                const data = await resp.json();
                await window.pdvOfflineDB.salvarCatalogo(data.empresa_id, data.produtos, data.clientes);
                console.log(`[PWA] Catálogo offline sincronizado: ${data.produtos?.length || 0} produtos.`);
            }
        } catch (e) {
            console.warn('[PWA] Não foi possível atualizar o catálogo offline em background:', e);
        }
    }

    focusBarcodeScanner() {
        const input = document.getElementById('barcode-input');
        if (input) {
            input.focus();
            input.select();
        }
    }

    closeModals() {
        document.querySelectorAll('.modal.show').forEach(m => {
            const instance = bootstrap.Modal.getInstance(m);
            if (instance) instance.hide();
        });
        this.resetModalPagamento();
        const dropdown = document.getElementById('search-results-dropdown');
        if (dropdown) dropdown.classList.add('d-none');
        this.focusBarcodeScanner();
    }

    // --- PERSISTÊNCIA DO CARRINHO EM LOCALSTORAGE ---

    salvarCarrinhoPersistido() {
        try {
            const cliSelect = document.getElementById('cliente-select');
            const data = {
                cart: this.cart,
                discountValue: this.discountValue,
                discountType: this.discountType,
                clienteId: cliSelect ? cliSelect.value : null,
                payments: this.payments,
                currentSaleName: this.currentSaleName || '',
                selectedPaymentMethod: this.selectedPaymentMethod || 'DINHEIRO'
            };
            localStorage.setItem('pdv_current_cart', JSON.stringify(data));
        } catch (e) {
            console.warn('Erro ao salvar carrinho no localStorage:', e);
        }
    }

    carregarCarrinhoPersistido() {
        try {
            const raw = localStorage.getItem('pdv_current_cart');
            if (!raw) return;
            const data = JSON.parse(raw);
            if (data && Array.isArray(data.cart) && data.cart.length > 0) {
                this.cart = data.cart;
                this.discountValue = data.discountValue || 0.00;
                this.discountType = data.discountType || 'BRL';
                this.payments = Array.isArray(data.payments) ? data.payments : [];
                this.currentSaleName = data.currentSaleName || '';
                this.selectedPaymentMethod = data.selectedPaymentMethod || 'DINHEIRO';

                setTimeout(() => {
                    const cliSelect = document.getElementById('cliente-select');
                    if (cliSelect && data.clienteId) {
                        cliSelect.value = data.clienteId;
                    }
                    const discInput = document.getElementById('discount-input');
                    if (discInput && this.discountValue > 0) {
                        discInput.value = this.discountValue;
                    }
                    const discType = document.getElementById('discount-type-select');
                    if (discType) {
                        discType.value = this.discountType;
                    }
                    this.renderCart();
                }, 100);
            }
        } catch (e) {
            console.warn('Erro ao carregar carrinho persistido:', e);
        }
    }

    limparCarrinhoPersistido() {
        localStorage.removeItem('pdv_current_cart');
    }

    // --- MANIPULAÇÃO DO CARRINHO ---

    mostrarFeedback(mensagem, tipo = 'danger') {
        if (typeof window.mostrarFeedbackBip === 'function') {
            window.mostrarFeedbackBip(mensagem, tipo);
        } else {
            const fb = document.getElementById('bip-feedback');
            if (fb) {
                fb.className = `position-absolute end-0 top-0 mt-1 me-2 badge p-2 shadow bg-${tipo === 'danger' ? 'danger' : 'success'} text-white`;
                fb.innerHTML = `<i class="bi ${tipo === 'danger' ? 'bi-exclamation-triangle-fill' : 'bi-check-circle-fill'} me-1"></i> ${mensagem}`;
                fb.classList.remove('d-none');
                clearTimeout(window._bipFeedbackTimeout);
                window._bipFeedbackTimeout = setTimeout(() => { fb.classList.add('d-none'); }, 2500);
            } else {
                console.warn(`[PDV] ${tipo.toUpperCase()}: ${mensagem}`);
            }
        }
    }

    addItemToCart(produto, quantidadePrevia = null) {
        if (!produto || typeof produto !== 'object') {
            this.mostrarFeedback('Objeto de produto inválido.', 'danger');
            return false;
        }

        const rawId = produto.produto_id || produto.id;
        const prodId = parseInt(rawId, 10);
        if (isNaN(prodId) || prodId <= 0) {
            this.mostrarFeedback('Não foi possível identificar o código/ID do produto.', 'danger');
            return false;
        }

        const nome = (produto.nome || '').trim();
        if (!nome) {
            this.mostrarFeedback('Produto sem identificação de nome válida.', 'danger');
            return false;
        }

        // Validação estrita do preço de venda (NUNCA aceitar 0, NaN, undefined, null ou vazio)
        let preco = null;
        const camposPreco = [
            produto.preco_venda,
            produto.preco,
            produto.preco_venda_unitario,
            produto.valor_unitario,
            produto.valor,
            produto.unit_price,
            produto.price
        ];
        for (const p of camposPreco) {
            if (p !== undefined && p !== null && p !== '') {
                if (typeof p === 'number' && !isNaN(p) && p > 0) {
                    preco = p;
                    break;
                }
                if (typeof p === 'string' && p.trim() !== '') {
                    const parsed = parseFloat(p.replace(',', '.'));
                    if (!isNaN(parsed) && parsed > 0) {
                        preco = parsed;
                        break;
                    }
                }
            }
        }

        if (preco === null || isNaN(preco) || preco <= 0) {
            this.mostrarFeedback(`Não foi possível adicionar "${nome}" porque o preço de venda é inválido ou não foi identificado.`, 'danger');
            return false;
        }

        preco = roundMoney(preco);

        // Validação de quantidade
        let qtd = 1.0;
        if (quantidadePrevia !== null && !isNaN(parseFloat(quantidadePrevia)) && parseFloat(quantidadePrevia) > 0) {
            qtd = parseFloat(quantidadePrevia);
        } else {
            const qtdInput = document.getElementById('qtd-input');
            if (qtdInput && qtdInput.value) {
                const parsedQtd = parseFloat(String(qtdInput.value).replace(',', '.'));
                if (!isNaN(parsedQtd) && parsedQtd > 0) {
                    qtd = parsedQtd;
                }
            }
        }
        qtd = Math.round((qtd + Number.EPSILON) * 1000) / 1000;

        const existingIndex = this.cart.findIndex(i => i.produto_id === prodId);

        if (existingIndex > -1) {
            this.cart[existingIndex].quantidade = Math.round((this.cart[existingIndex].quantidade + qtd) * 1000) / 1000;
            this.cart[existingIndex].subtotal = roundMoney(this.cart[existingIndex].quantidade * this.cart[existingIndex].preco_venda);
        } else {
            this.cart.push({
                produto_id: prodId,
                nome: nome,
                codigo_barras: (produto.codigo_barras || '').trim(),
                sku: (produto.sku || '').trim(),
                quantidade: qtd,
                preco_venda: preco,
                subtotal: roundMoney(qtd * preco)
            });
        }

        const qtdEl = document.getElementById('qtd-input');
        if (qtdEl) qtdEl.value = '1';

        this.salvarCarrinhoPersistido();
        this.renderCart();
        this.focusBarcodeScanner();
        return true;
    }

    addDividaToCart(dividaData) {
        if (this.cart.some(i => i.tipo_item === 'RECEBIMENTO_DIVIDA')) {
            alert('Já existe uma operação de recebimento de dívida neste checkout. Finalize ou remova a operação atual antes de adicionar outra.');
            return false;
        }

        const virtualItem = {
            tipo_item: 'RECEBIMENTO_DIVIDA',
            cliente_id: dividaData.cliente_id,
            cliente_nome: dividaData.cliente_nome,
            divida_total: roundMoney(dividaData.divida_total),
            valor_pago: roundMoney(dividaData.valor_pago),
            valor_abatimento: roundMoney(dividaData.valor_abatimento),
            motivo_abatimento: dividaData.motivo_abatimento || '',
            total_liquidado: roundMoney(dividaData.total_liquidado),
            nome: `RECEBIMENTO DE DÍVIDA - ${dividaData.cliente_nome}`,
            preco_venda: roundMoney(dividaData.valor_pago),
            subtotal: roundMoney(dividaData.valor_pago),
            quantidade: 1
        };

        this.cart.push(virtualItem);

        // Fixa e trava o cliente no checkout
        this.setClient(dividaData.cliente_id, true);

        this.salvarCarrinhoPersistido();
        this.renderCart();
        this.updateNetworkBadge();
        return true;
    }

    setClient(clienteId, isForcedByDebt = false) {
        const debtItem = this.cart.find(i => i.tipo_item === 'RECEBIMENTO_DIVIDA');
        const cliSelect = document.getElementById('cliente-select');
        const lockBadge = document.getElementById('cliente-lock-badge');
        const lockMsg = document.getElementById('cliente-lock-msg');

        if (debtItem) {
            const requiredId = String(debtItem.cliente_id);
            if (clienteId && String(clienteId) !== requiredId && !isForcedByDebt) {
                alert(`Este checkout possui um recebimento de dívida de ${debtItem.cliente_nome}. O cliente do checkout deve ser o mesmo cliente da dívida.`);
                if (cliSelect) cliSelect.value = requiredId;
                return false;
            }
            this.cliente_id = parseInt(requiredId, 10);
            if (cliSelect) {
                cliSelect.value = requiredId;
                cliSelect.disabled = true;
            }
            if (lockBadge) lockBadge.classList.remove('d-none');
            if (lockMsg) lockMsg.classList.remove('d-none');
        } else {
            this.cliente_id = clienteId ? parseInt(clienteId, 10) : null;
            if (cliSelect) {
                cliSelect.disabled = false;
            }
            if (lockBadge) lockBadge.classList.add('d-none');
            if (lockMsg) lockMsg.classList.add('d-none');
        }
        this.salvarCarrinhoPersistido();
        return true;
    }

    unlockClienteCheckout() {
        const cliSelect = document.getElementById('cliente-select');
        const lockBadge = document.getElementById('cliente-lock-badge');
        const lockMsg = document.getElementById('cliente-lock-msg');
        if (cliSelect) cliSelect.disabled = false;
        if (lockBadge) lockBadge.classList.add('d-none');
        if (lockMsg) lockMsg.classList.add('d-none');
    }

    removeItem(index) {
        if (index >= 0 && index < this.cart.length) {
            const item = this.cart[index];
            this.cart.splice(index, 1);
            if (item.tipo_item === 'RECEBIMENTO_DIVIDA') {
                this.unlockClienteCheckout();
            }
            this.salvarCarrinhoPersistido();
            this.renderCart();
            this.focusBarcodeScanner();
        }
    }

    updateItemQuantity(index, newQty) {
        const item = this.cart[index];
        if (!item) return;

        if (item.tipo_item === 'RECEBIMENTO_DIVIDA') {
            alert('A quantidade da operação de recebimento de dívida é fixa.');
            this.renderCart();
            return;
        }

        const val = parseFloat(String(newQty).replace(',', '.'));
        if (isNaN(val) || val <= 0) {
            this.removeItem(index);
            return;
        }
        this.cart[index].quantidade = Math.round((val + Number.EPSILON) * 1000) / 1000;
        this.cart[index].subtotal = roundMoney(this.cart[index].quantidade * this.cart[index].preco_venda);
        this.salvarCarrinhoPersistido();
        this.renderCart();
    }

    clearCart() {
        this.cart = [];
        this.payments = [];
        this.selectedCustomer = null;
        this.cliente_id = null;
        this.discountValue = 0.00;
        this.discountType = 'BRL';
        this.currentSaleName = '';

        this.unlockClienteCheckout();
        const cliSelect = document.getElementById('cliente-select');
        if (cliSelect) cliSelect.value = '';
        const discInput = document.getElementById('discount-input');
        if (discInput) discInput.value = '';

        this.limparCarrinhoPersistido();
        this.renderCart();
        this.focusBarcodeScanner();
    }

    // --- CÁLCULOS E TOTAIS COM PRECISÃO MONETÁRIA ---

    getSubtotalProdutos() {
        return roundMoney(this.cart.filter(i => i.tipo_item !== 'RECEBIMENTO_DIVIDA').reduce((acc, item) => acc + item.subtotal, 0.00));
    }

    getValorDivida() {
        return roundMoney(this.cart.filter(i => i.tipo_item === 'RECEBIMENTO_DIVIDA').reduce((acc, item) => acc + item.valor_pago, 0.00));
    }

    getSubtotal() {
        return roundMoney(this.getSubtotalProdutos() + this.getValorDivida());
    }

    getDiscountAmount() {
        const subtotalProd = this.getSubtotalProdutos();
        if (subtotalProd <= 0) return 0.00;

        if (this.discountType === 'PERCENT') {
            return roundMoney((subtotalProd * this.discountValue) / 100.00);
        }
        return roundMoney(Math.min(subtotalProd, this.discountValue));
    }

    getTotal() {
        const totalProd = Math.max(0.00, roundMoney(this.getSubtotalProdutos() - this.getDiscountAmount()));
        return roundMoney(totalProd + this.getValorDivida());
    }

    getTotalPaid() {
        return roundMoney(this.payments.reduce((acc, p) => acc + p.valor, 0.00));
    }

    getTotalPaidEffective() {
        return roundMoney(this.payments.reduce((acc, p) => acc + (p.valor - p.troco), 0.00));
    }

    getTotalTroco() {
        return roundMoney(this.payments.reduce((acc, p) => acc + p.troco, 0.00));
    }

    getRemainingToPay() {
        return Math.max(0.00, roundMoney(this.getTotal() - this.getTotalPaidEffective()));
    }

    updateDiscount(type, value) {
        this.discountType = type === 'PERCENT' ? 'PERCENT' : 'BRL';
        const parsed = parseFloat(String(value).replace(',', '.'));
        this.discountValue = isNaN(parsed) || parsed < 0 ? 0.00 : parsed;
        this.salvarCarrinhoPersistido();
        this.renderCart();
    }

    // --- RENDERIZAÇÃO DA INTERFACE ---

    renderCart() {
        const tbody = document.getElementById('cart-table-body');
        const countBadge = document.getElementById('cart-items-count');
        const subtotalEl = document.getElementById('summary-subtotal');
        const discountEl = document.getElementById('summary-discount');
        const totalEl = document.getElementById('summary-total');
        const totalPayEl = document.getElementById('summary-total-pay');

        if (!tbody) return;

        tbody.innerHTML = '';

        if (this.cart.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center text-muted py-5">
                        <i class="bi bi-cart-x fs-1 d-block mb-2 text-secondary opacity-50"></i>
                        Carrinho Vazio (Escaneie ou escolha um produto)
                    </td>
                </tr>
            `;
            this.unlockClienteCheckout();
        } else {
            const debt = this.cart.find(i => i.tipo_item === 'RECEBIMENTO_DIVIDA');
            if (debt) {
                this.setClient(debt.cliente_id, true);
            }

            this.cart.forEach((item, idx) => {
                const tr = document.createElement('tr');
                if (item.tipo_item === 'RECEBIMENTO_DIVIDA') {
                    tr.className = 'table-info-subtle';
                    tr.innerHTML = `
                        <td colspan="2">
                            <div class="d-flex align-items-center gap-2">
                                <span class="badge bg-info text-dark fw-bold"><i class="bi bi-cash-stack me-1"></i> RECEBIMENTO DE DÍVIDA</span>
                                <strong class="text-dark">Cliente: ${item.cliente_nome}</strong>
                            </div>
                            <small class="text-muted d-block mt-1">
                                ${item.valor_abatimento > 0 ? `Abatimento: <strong>R$ ${item.valor_abatimento.toFixed(2).replace('.', ',')}</strong> | ` : ''}
                                Total Liquidado: <strong>R$ ${item.total_liquidado.toFixed(2).replace('.', ',')}</strong>
                                ${item.motivo_abatimento ? ` | Motivo: <em>${item.motivo_abatimento}</em>` : ''}
                            </small>
                        </td>
                        <td class="fw-bold text-muted text-center">1x</td>
                        <td class="fw-bold text-primary">R$ ${item.valor_pago.toFixed(2).replace('.', ',')}</td>
                        <td class="text-end">
                            <button class="btn btn-outline-danger btn-sm py-0 px-2" onclick="pdvApp.removeItem(${idx})" title="Remover Recebimento de Dívida">
                                <i class="bi bi-trash"></i>
                            </button>
                        </td>
                    `;
                } else {
                    tr.innerHTML = `
                        <td>
                            <strong class="text-dark d-block">${item.nome}</strong>
                            <small class="text-muted font-monospace">${item.codigo_barras || 'S/ Código'}</small>
                        </td>
                        <td class="text-center">
                            <div class="input-group input-group-sm justify-content-center" style="max-width: 130px; margin: 0 auto;">
                                <button class="btn btn-outline-secondary" type="button" onclick="pdvApp.updateItemQuantity(${idx}, ${item.quantidade - 1})">-</button>
                                <input type="number" class="form-control text-center fw-bold" value="${item.quantidade}" min="0.001" step="any" onchange="pdvApp.updateItemQuantity(${idx}, this.value)">
                                <button class="btn btn-outline-secondary" type="button" onclick="pdvApp.updateItemQuantity(${idx}, ${item.quantidade + 1})">+</button>
                            </div>
                        </td>
                        <td class="fw-bold">R$ ${item.preco_venda.toFixed(2).replace('.', ',')}</td>
                        <td class="fw-bold text-success">R$ ${item.subtotal.toFixed(2).replace('.', ',')}</td>
                        <td class="text-end">
                            <button class="btn btn-outline-danger btn-sm py-0 px-2" onclick="pdvApp.removeItem(${idx})">
                                <i class="bi bi-trash"></i>
                            </button>
                        </td>
                    `;
                }
                tbody.appendChild(tr);
            });
        }

        const subtotal = this.getSubtotal();
        const discount = this.getDiscountAmount();
        const total = this.getTotal();

        if (countBadge) countBadge.innerText = this.cart.reduce((acc, i) => acc + (i.tipo_item === 'RECEBIMENTO_DIVIDA' ? 1 : i.quantidade), 0);
        if (subtotalEl) subtotalEl.innerText = `R$ ${subtotal.toFixed(2).replace('.', ',')}`;
        if (discountEl) discountEl.innerText = `- R$ ${discount.toFixed(2).replace('.', ',')}`;
        if (totalEl) totalEl.innerText = `R$ ${total.toFixed(2).replace('.', ',')}`;
        if (totalPayEl) totalPayEl.innerText = `R$ ${total.toFixed(2).replace('.', ',')}`;

        this.updateNetworkBadge();
    }

    // --- PAUSA E RETOMADA DE VENDAS (COM NOME FIXO E PERSISTÊNCIA) ---

    pausarVendaAtual() {
        if (this.cart.length === 0) {
            alert('Não há itens no carrinho para pausar.');
            return;
        }

        const cliSelect = document.getElementById('cliente-select');
        const clienteNome = cliSelect && cliSelect.selectedOptions[0] ? cliSelect.selectedOptions[0].text : 'Consumidor';

        const nomeSugerido = this.currentSaleName || `Venda ${new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`;
        const nomeInformado = prompt('Identificação / Nome da Venda Pausada:', nomeSugerido);
        if (nomeInformado === null) {
            return; // Cancelou o prompt
        }

        const nomeFinal = nomeInformado.trim() || nomeSugerido;
        this.currentSaleName = nomeFinal;

        const pausedSale = {
            id: Date.now(),
            nome: nomeFinal,
            cart: [...this.cart],
            clienteId: cliSelect ? cliSelect.value : null,
            clienteNome: clienteNome,
            desconto: this.discountValue,
            descontoTipo: this.discountType,
            dataHora: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
        };

        this.pausedSales.push(pausedSale);
        localStorage.setItem('pdv_paused_sales', JSON.stringify(this.pausedSales));

        this.clearCart();
        this.currentSaleName = '';
        this.updatePausedBadge();
        alert(`Venda "${nomeFinal}" pausada com sucesso! Você pode retomá-la a qualquer momento.`);
    }

    resumeSale(id) {
        const idx = this.pausedSales.findIndex(s => s.id === id);
        if (idx === -1) return;

        if (this.cart.length > 0) {
            if (!confirm('O carrinho atual possui itens. Deseja substituí-los pela venda pausada?')) {
                return;
            }
        }

        const sale = this.pausedSales.splice(idx, 1)[0];
        localStorage.setItem('pdv_paused_sales', JSON.stringify(this.pausedSales));

        this.cart = sale.cart;
        this.discountValue = sale.desconto;
        this.discountType = sale.descontoTipo;
        this.currentSaleName = sale.nome || '';

        const cliSelect = document.getElementById('cliente-select');
        if (cliSelect && sale.clienteId) {
            cliSelect.value = sale.clienteId;
        }

        this.salvarCarrinhoPersistido();
        this.renderCart();
        this.updatePausedBadge();
        this.closeModals();
    }

    abrirModalVendasEmEspera() {
        const modalEl = document.getElementById('pausedSalesModal');
        const listEl = document.getElementById('paused-sales-list');
        if (!modalEl || !listEl) return;

        if (this.pausedSales.length === 0) {
            listEl.innerHTML = `
                <div class="text-center py-4 text-muted">
                    <i class="bi bi-inbox fs-1 d-block mb-2 text-secondary opacity-50"></i>
                    Nenhuma venda em espera no momento.
                </div>
            `;
        } else {
            let html = '<div class="list-group">';
            this.pausedSales.forEach((s) => {
                const totalVenda = s.cart.reduce((acc, i) => acc + i.subtotal, 0.00);
                const qtdItens = s.cart.reduce((acc, i) => acc + i.quantidade, 0);
                html += `
                    <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center p-3 mb-2 rounded border">
                        <div>
                            <h6 class="fw-bold text-primary mb-1"><i class="bi bi-pause-circle me-1"></i>${s.nome || 'Venda sem Nome'}</h6>
                            <small class="text-muted d-block">
                                Cliente: <strong>${s.clienteNome || 'Consumidor'}</strong> | ${qtdItens} item(ns) | Horário: ${s.dataHora}
                            </small>
                        </div>
                        <div class="d-flex align-items-center gap-2">
                            <span class="fs-5 fw-bold text-success me-2">R$ ${totalVenda.toFixed(2).replace('.', ',')}</span>
                            <button class="btn btn-primary btn-sm fw-bold" onclick="pdvApp.resumeSale(${s.id})">
                                <i class="bi bi-play-fill me-1"></i> Retomar
                            </button>
                            <button class="btn btn-outline-danger btn-sm" onclick="pdvApp.excluirVendaPausada(${s.id})">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            listEl.innerHTML = html;
        }

        const modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
        modal.show();
    }

    excluirVendaPausada(id) {
        if (!confirm('Deseja excluir esta venda em espera?')) return;
        this.pausedSales = this.pausedSales.filter(s => s.id !== id);
        localStorage.setItem('pdv_paused_sales', JSON.stringify(this.pausedSales));
        this.updatePausedBadge();
        this.abrirModalVendasEmEspera();
    }

    updatePausedBadge() {
        const badge = document.getElementById('paused-sales-badge') || document.getElementById('paused-sales-count');
        if (badge) {
            badge.innerText = this.pausedSales.length;
            badge.style.display = this.pausedSales.length > 0 ? 'inline-block' : 'none';
            badge.classList.toggle('d-none', this.pausedSales.length === 0);
        }
    }

    // --- MODAL DE PAGAMENTO & FLUXO REFINADO ---

    resetModalPagamento() {
        this.payments = [];
        this.selectedPaymentMethod = 'DINHEIRO';
        const crediarioBox = document.getElementById('modal-crediario-customer-box');
        if (crediarioBox) crediarioBox.classList.add('d-none');
        this.salvarCarrinhoPersistido();
    }

    abrirModalPagamento() {
        if (this.cart.length === 0) {
            alert('Adicione ao menos um produto no carrinho antes de prosseguir para o pagamento.');
            this.focusBarcodeScanner();
            return;
        }

        // Toda nova entrada a partir do carrinho começa limpa
        this.isTransitioningToConfirm = false;
        this.isTransitioningToPayment = false;
        this.resetModalPagamento();

        const cliSelectMain = document.getElementById('cliente-select');
        const cliSelectModal = document.getElementById('modal-cliente-select');
        if (cliSelectMain && cliSelectModal) {
            cliSelectModal.value = cliSelectMain.value;
        }

        const modalEl = document.getElementById('paymentModal');
        if (modalEl) {
            const modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
            modal.show();
            this.selecionarFormaPagamento('DINHEIRO');
            this.renderPaymentModal();
        }
    }

    selecionarFormaPagamento(forma) {
        this.selectedPaymentMethod = forma || 'DINHEIRO';

        // Atualiza estilo dos botões rápidos
        ['btn-pay-dinheiro', 'btn-pay-pix', 'btn-pay-debito', 'btn-pay-credito'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.remove('active');
        });

        const activeMap = {
            'DINHEIRO': 'btn-pay-dinheiro',
            'PIX': 'btn-pay-pix',
            'CARTAO_DEBITO': 'btn-pay-debito',
            'CARTAO_CREDITO': 'btn-pay-credito'
        };
        const activeBtn = document.getElementById(activeMap[forma]);
        if (activeBtn) activeBtn.classList.add('active');

        // Atualiza label do input
        const lbl = document.getElementById('label-pay-valor');
        if (lbl) {
            if (forma === 'DINHEIRO') {
                lbl.innerText = 'Valor Recebido (R$):';
            } else {
                const nomes = { 'PIX': 'PIX', 'CARTAO_DEBITO': 'Cartão Débito', 'CARTAO_CREDITO': 'Cartão Crédito', 'CREDIARIO': 'Fiado' };
                lbl.innerText = `Valor a Pagar em ${nomes[forma] || forma} (R$):`;
            }
        }

        const crediarioBox = document.getElementById('modal-crediario-customer-box');
        if (crediarioBox && forma !== 'CREDIARIO') {
            crediarioBox.classList.add('d-none');
        }

        const remaining = this.getRemainingToPay();
        const valorInput = document.getElementById('modal-pay-valor');
        if (valorInput) {
            if (remaining > 0) {
                valorInput.value = remaining.toFixed(2);
            }
            valorInput.focus();
            valorInput.select();
            setTimeout(() => {
                valorInput.focus();
                valorInput.select();
            }, 50);
        }

        this.onValorRecebidoInput();
    }

    toggleCrediarioBox(forceOpen = false) {
        const crediarioBox = document.getElementById('modal-crediario-customer-box');
        if (!crediarioBox) return;

        const isCurrentlyHidden = crediarioBox.classList.contains('d-none');
        if (forceOpen || isCurrentlyHidden) {
            crediarioBox.classList.remove('d-none');
            this.selectedPaymentMethod = 'CREDIARIO';
            ['btn-pay-dinheiro', 'btn-pay-pix', 'btn-pay-debito', 'btn-pay-credito'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.classList.remove('active');
            });
            const lbl = document.getElementById('label-pay-valor');
            if (lbl) lbl.innerText = 'Valor no Fiado / Crediário (R$):';
            this.validarLimiteClienteModal();
        } else {
            crediarioBox.classList.add('d-none');
            this.selecionarFormaPagamento('DINHEIRO');
        }
    }

    onCrediarioCustomerChange(selectEl) {
        if (selectEl && selectEl.value) {
            const mainCliSelect = document.getElementById('cliente-select');
            if (mainCliSelect) mainCliSelect.value = selectEl.value;
        }
        this.validarLimiteClienteModal();
    }

    validarLimiteClienteModal() {
        const cliSelect = document.getElementById('modal-cliente-select') || document.getElementById('cliente-select');
        const infoBox = document.getElementById('modal-crediario-credit-info');
        if (!infoBox) return;

        if (!cliSelect || !cliSelect.value) {
            infoBox.className = 'alert alert-warning mt-2 mb-0';
            infoBox.classList.remove('d-none');
            infoBox.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-1"></i> Selecione um cliente para validar o limite disponível.';
            return;
        }

        const opt = cliSelect.selectedOptions[0];
        const limite = parseFloat(opt.dataset.limite || '0.00');
        const devedor = parseFloat(opt.dataset.devedor || '0.00');
        const disponivel = parseFloat(opt.dataset.disponivel || '0.00');
        const nome = opt.text;
        const totalVenda = this.getTotal();

        infoBox.classList.remove('d-none');
        if (limite > 0 && totalVenda > disponivel) {
            infoBox.className = 'alert alert-danger mt-2 mb-0';
            infoBox.innerHTML = `
                <strong><i class="bi bi-x-circle-fill me-1"></i> Limite de Crédito Insuficiente!</strong><br>
                Cliente: <strong>${nome}</strong> | Limite: R$ ${limite.toFixed(2)} | Devedor: R$ ${devedor.toFixed(2)}<br>
                Crédito Disponível: <strong class="text-danger">R$ ${disponivel.toFixed(2)}</strong> (Venda: R$ ${totalVenda.toFixed(2)})
            `;
        } else {
            const aposVenda = Math.max(0, disponivel - totalVenda);
            infoBox.className = 'alert alert-success mt-2 mb-0';
            infoBox.innerHTML = `
                <strong><i class="bi bi-check-circle-fill me-1"></i> Limite de Crédito Aprovado!</strong><br>
                Cliente: <strong>${nome}</strong> | Crédito Disponível: <strong>R$ ${disponivel.toFixed(2)}</strong><br>
                Saldo restante após esta venda: <strong class="text-success">R$ ${aposVenda.toFixed(2)}</strong>
            `;
        }
    }

    onValorRecebidoInput() {
        const totalVenda = this.getTotal();
        const totalPaidEffective = this.getTotalPaidEffective();
        const remainingBefore = Math.max(0.00, roundMoney(totalVenda - totalPaidEffective));

        const valorInput = document.getElementById('modal-pay-valor');
        const inputVal = valorInput ? parseFloat(String(valorInput.value).replace(',', '.')) : 0.00;
        const currentVal = isNaN(inputVal) || inputVal < 0 ? 0.00 : roundMoney(inputVal);

        const forma = this.selectedPaymentMethod || 'DINHEIRO';

        let novoFalta = remainingBefore;
        let novoTroco = this.getTotalTroco();
        let totalPagoDisplay = totalPaidEffective;

        if (forma === 'DINHEIRO') {
            if (currentVal >= remainingBefore) {
                novoTroco = roundMoney(this.getTotalTroco() + (currentVal - remainingBefore));
                novoFalta = 0.00;
                totalPagoDisplay = totalVenda;
            } else {
                novoFalta = roundMoney(remainingBefore - currentVal);
                totalPagoDisplay = roundMoney(totalPaidEffective + currentVal);
            }
        } else {
            // PIX / CRÉDITO / DÉBITO nunca geram troco
            if (currentVal >= remainingBefore) {
                novoFalta = 0.00;
                totalPagoDisplay = totalVenda;
            } else {
                novoFalta = roundMoney(remainingBefore - currentVal);
                totalPagoDisplay = roundMoney(totalPaidEffective + currentVal);
            }
        }

        const paidEl = document.getElementById('modal-display-pago');
        const remEl = document.getElementById('modal-display-restante');
        const trocoEl = document.getElementById('modal-display-troco');
        const btnFinalizar = document.getElementById('modal-btn-finalizar');

        if (paidEl) paidEl.innerText = `R$ ${totalPagoDisplay.toFixed(2).replace('.', ',')}`;
        if (remEl) remEl.innerText = `R$ ${novoFalta.toFixed(2).replace('.', ',')}`;
        if (trocoEl) trocoEl.innerText = `R$ ${novoTroco.toFixed(2).replace('.', ',')}`;

        if (btnFinalizar) {
            const isCovered = (remainingBefore <= 0.001 && this.payments.length > 0) || (currentVal >= remainingBefore - 0.001 && remainingBefore > 0);
            btnFinalizar.disabled = !isCovered;
            if (isCovered) {
                btnFinalizar.classList.remove('btn-secondary');
                btnFinalizar.classList.add('btn-success');
            } else {
                btnFinalizar.classList.remove('btn-success');
                btnFinalizar.classList.add('btn-secondary');
            }
        }
    }

    adicionarParcelaPagamento() {
        if (this._isAddingPayment) return;
        this._isAddingPayment = true;
        setTimeout(() => { this._isAddingPayment = false; }, 300);

        const forma = this.selectedPaymentMethod || 'DINHEIRO';
        const valorInput = document.getElementById('modal-pay-valor');
        if (!valorInput) {
            this._isAddingPayment = false;
            return;
        }

        const remaining = this.getRemainingToPay();
        if (remaining <= 0.001) {
            this._isAddingPayment = false;
            this.abrirModalConfirmacao();
            return;
        }

        let val = parseFloat(String(valorInput.value).replace(',', '.'));
        if (isNaN(val) || val <= 0) {
            val = remaining;
        }
        val = roundMoney(val);

        if (forma === 'CREDIARIO') {
            const cliSelect = document.getElementById('modal-cliente-select') || document.getElementById('cliente-select');
            if (!cliSelect || !cliSelect.value) {
                this._isAddingPayment = false;
                alert('Para lançar parcela no Crediário / Fiado é obrigatório selecionar um cliente.');
                this.toggleCrediarioBox(true);
                return;
            }
        }

        let valorRegistrado = val;
        let troco = 0.00;

        if (forma === 'DINHEIRO') {
            if (val > remaining) {
                valorRegistrado = val;
                troco = roundMoney(val - remaining);
            }
        } else {
            if (val > remaining + 0.001) {
                this._isAddingPayment = false;
                alert(`Para pagamentos em ${forma}, o valor não pode exceder o saldo restante (R$ ${remaining.toFixed(2).replace('.', ',')}).`);
                valorInput.value = remaining.toFixed(2);
                valorInput.focus();
                return;
            }
            valorRegistrado = Math.min(val, remaining);
        }

        this.payments.push({
            forma: forma,
            valor: roundMoney(valorRegistrado),
            troco: roundMoney(troco)
        });

        this.salvarCarrinhoPersistido();
        this.renderPaymentModal();

        const novoRestante = this.getRemainingToPay();
        if (novoRestante > 0) {
            valorInput.value = novoRestante.toFixed(2);
            valorInput.focus();
            valorInput.select();
            setTimeout(() => {
                valorInput.focus();
                valorInput.select();
            }, 50);
        } else {
            valorInput.value = '0.00';
            this.abrirModalConfirmacao();
        }
    }

    removerParcelaPagamento(index) {
        if (index >= 0 && index < this.payments.length) {
            this.payments.splice(index, 1);
            this.salvarCarrinhoPersistido();
            this.renderPaymentModal();
            const valorInput = document.getElementById('modal-pay-valor');
            if (valorInput) {
                const remaining = this.getRemainingToPay();
                if (remaining > 0) {
                    valorInput.value = remaining.toFixed(2);
                }
                valorInput.focus();
                valorInput.select();
            }
        }
    }

    renderPaymentModal() {
        const totalVenda = this.getTotal();
        const totalPaid = this.getTotalPaidEffective();
        const remaining = Math.max(0.00, roundMoney(totalVenda - totalPaid));
        const totalTroco = this.getTotalTroco();

        const totalEl = document.getElementById('modal-display-total');
        const paidEl = document.getElementById('modal-display-pago');
        const remEl = document.getElementById('modal-display-restante');
        const trocoEl = document.getElementById('modal-display-troco');
        const listEl = document.getElementById('modal-payments-list');
        const sectionEl = document.getElementById('modal-payments-section');
        const btnFinalizar = document.getElementById('modal-btn-finalizar');
        const valorInput = document.getElementById('modal-pay-valor');

        if (totalEl) totalEl.innerText = `R$ ${totalVenda.toFixed(2).replace('.', ',')}`;
        if (paidEl) paidEl.innerText = `R$ ${totalPaid.toFixed(2).replace('.', ',')}`;
        if (remEl) remEl.innerText = `R$ ${remaining.toFixed(2).replace('.', ',')}`;
        if (trocoEl) trocoEl.innerText = `R$ ${totalTroco.toFixed(2).replace('.', ',')}`;

        if (valorInput && remaining > 0) {
            valorInput.value = remaining.toFixed(2);
        }

        if (sectionEl) {
            sectionEl.classList.toggle('d-none', this.payments.length === 0);
        }

        if (listEl) {
            listEl.innerHTML = '';
            const nomesFormas = {
                'DINHEIRO': 'Dinheiro',
                'PIX': 'PIX',
                'CARTAO_DEBITO': 'Cartão Débito',
                'CARTAO_CREDITO': 'Cartão Crédito',
                'CREDIARIO': 'Fiado / Crediário'
            };

            this.payments.forEach((p, idx) => {
                const div = document.createElement('div');
                div.className = 'd-flex justify-content-between align-items-center bg-light border rounded p-2 mb-2 text-dark';

                let det = `<strong class="text-dark">${nomesFormas[p.forma] || p.forma}</strong>: <span class="fw-bold text-dark">R$ ${(p.valor - p.troco).toFixed(2).replace('.', ',')}</span>`;
                if (p.forma === 'DINHEIRO' && p.troco > 0) {
                    det += ` <small class="text-secondary">(Recebido: R$ ${p.valor.toFixed(2).replace('.', ',')} | Troco: R$ ${p.troco.toFixed(2).replace('.', ',')})</small>`;
                }

                div.innerHTML = `
                    <div class="text-dark">${det}</div>
                    <button type="button" class="btn btn-outline-danger btn-sm py-0 px-2" onclick="pdvApp.removerParcelaPagamento(${idx})" title="Remover parcela">
                        <i class="bi bi-x-lg"></i>
                    </button>
                `;
                listEl.appendChild(div);
            });
        }

        this.onValorRecebidoInput();
    }

    // --- MODAL DE CONFIRMAÇÃO FINAL PRÉ-GRAVAÇÃO ---

    abrirModalConfirmacao() {
        if (this.cart.length === 0) {
            alert('Adicione ao menos um produto no carrinho antes de prosseguir.');
            return;
        }

        const totalVenda = this.getTotal();
        let remaining = this.getRemainingToPay();

        // Se ainda resta saldo a pagar E há valor no input / forma selecionada:
        // O botão FINALIZAR adiciona automaticamente a parcela restante pendente!
        if (remaining > 0.001) {
            const valorInput = document.getElementById('modal-pay-valor');
            const forma = this.selectedPaymentMethod || 'DINHEIRO';
            let val = valorInput ? parseFloat(String(valorInput.value).replace(',', '.')) : NaN;

            if (isNaN(val) || val <= 0) {
                val = remaining;
            }
            val = roundMoney(val);

            if (forma === 'CREDIARIO') {
                const cliSelect = document.getElementById('modal-cliente-select') || document.getElementById('cliente-select');
                if (!cliSelect || !cliSelect.value) {
                    alert('Vendas contendo parcelas no Crediário / Fiado exigem a seleção de um Cliente.');
                    this.toggleCrediarioBox(true);
                    return;
                }
            }

            let troco = 0.00;
            let valorRegistrado = val;

            if (forma === 'DINHEIRO') {
                if (val < remaining - 0.001) {
                    alert(`O valor em dinheiro (R$ ${val.toFixed(2).replace('.', ',')}) é insuficiente para cobrir o saldo restante de R$ ${remaining.toFixed(2).replace('.', ',')}.`);
                    if (valorInput) valorInput.focus();
                    return;
                }
                if (val > remaining) {
                    troco = roundMoney(val - remaining);
                }
            } else {
                if (val < remaining - 0.001) {
                    alert(`O valor informado em ${forma} (R$ ${val.toFixed(2).replace('.', ',')}) é insuficiente para cobrir o saldo restante de R$ ${remaining.toFixed(2).replace('.', ',')}.`);
                    if (valorInput) valorInput.focus();
                    return;
                }
                if (val > remaining + 0.001) {
                    alert(`Para pagamentos em ${forma}, o valor não pode ultrapassar o saldo restante (R$ ${remaining.toFixed(2).replace('.', ',')}).`);
                    if (valorInput) valorInput.focus();
                    return;
                }
                valorRegistrado = remaining; // Garante o valor líquido exato
            }

            // Adiciona a última parcela automaticamente sem duplicar
            this.payments.push({
                forma: forma,
                valor: roundMoney(valorRegistrado),
                troco: roundMoney(troco)
            });

            this.salvarCarrinhoPersistido();
            remaining = this.getRemainingToPay();
        }

        // Se após a validação ainda restar saldo
        if (remaining > 0.001) {
            alert(`Ainda resta um saldo de R$ ${remaining.toFixed(2).replace('.', ',')} a ser pago.`);
            return;
        }

        const temCrediario = this.payments.some(p => p.forma === 'CREDIARIO');
        const cliSelect = document.getElementById('modal-cliente-select') || document.getElementById('cliente-select');
        if (temCrediario && (!cliSelect || !cliSelect.value)) {
            alert('Vendas contendo parcelas no Crediário / Fiado exigem a seleção de um Cliente.');
            this.toggleCrediarioBox(true);
            return;
        }

        const nomesFormas = {
            'DINHEIRO': 'Dinheiro',
            'PIX': 'PIX',
            'CARTAO_DEBITO': 'Cartão Débito',
            'CARTAO_CREDITO': 'Cartão Crédito',
            'CREDIARIO': 'Fiado / Crediário'
        };

        const totalEl = document.getElementById('confirm-modal-total');
        const breakdownEl = document.getElementById('confirm-modal-payments-breakdown');
        const trocoBox = document.getElementById('confirm-modal-troco-box');
        const trocoEl = document.getElementById('confirm-modal-troco');
        const countEl = document.getElementById('confirm-modal-items-count');

        if (totalEl) totalEl.innerText = `R$ ${totalVenda.toFixed(2).replace('.', ',')}`;
        if (countEl) countEl.innerText = this.cart.reduce((acc, i) => acc + i.quantidade, 0);

        let totalTroco = 0.00;
        if (breakdownEl) {
            let html = '<ul class="list-unstyled mb-0 text-dark">';
            this.payments.forEach(p => {
                const valorLiquido = roundMoney(p.valor - p.troco);
                html += `<li class="d-flex justify-content-between py-1 border-bottom text-dark">
                    <span class="text-dark"><strong>${nomesFormas[p.forma] || p.forma}</strong></span>
                    <span class="fw-bold text-dark">R$ ${valorLiquido.toFixed(2).replace('.', ',')}</span>
                </li>`;
                if (p.troco > 0) totalTroco = roundMoney(totalTroco + p.troco);
            });
            html += '</ul>';
            breakdownEl.innerHTML = html;
        }

        if (trocoBox && trocoEl) {
            if (totalTroco > 0) {
                trocoBox.classList.remove('d-none');
                trocoEl.innerText = `R$ ${totalTroco.toFixed(2).replace('.', ',')}`;
            } else {
                trocoBox.classList.add('d-none');
            }
        }

        this.isTransitioningToConfirm = true;
        // Esconde modal de pagamento e exibe modal de confirmação
        const payModalEl = document.getElementById('paymentModal');
        const payModal = payModalEl ? bootstrap.Modal.getInstance(payModalEl) : null;
        if (payModal) payModal.hide();

        const confirmModalEl = document.getElementById('confirmSaleModal');
        if (confirmModalEl) {
            const confirmModal = bootstrap.Modal.getInstance(confirmModalEl) || new bootstrap.Modal(confirmModalEl);
            confirmModal.show();
            setTimeout(() => {
                this.isTransitioningToConfirm = false;
                const btnConfirm = document.getElementById('btn-efetivar-confirmacao');
                if (btnConfirm) btnConfirm.focus();
            }, 300);
        }
    }

    cancelarConfirmacaoVenda() {
        this.isTransitioningToPayment = true;
        const confirmModalEl = document.getElementById('confirmSaleModal');
        const confirmModal = confirmModalEl ? bootstrap.Modal.getInstance(confirmModalEl) : null;
        if (confirmModal) confirmModal.hide();

        const payModalEl = document.getElementById('paymentModal');
        if (payModalEl) {
            const payModal = bootstrap.Modal.getInstance(payModalEl) || new bootstrap.Modal(payModalEl);
            payModal.show();
            this.renderPaymentModal();
            setTimeout(() => {
                this.isTransitioningToPayment = false;
            }, 300);
        }
    }

    async confirmarEGravarVenda() {
        await this.executarFinalizacaoVenda();
    }

    // --- FINALIZAÇÃO E SINCRONIZAÇÃO DA VENDA (OFFLINE / ONLINE) ---

    async executarFinalizacaoVenda() {
        if (this.isProcessingSale) return;

        if (this.cart.length === 0) {
            alert('O carrinho está vazio.');
            return;
        }

        const remaining = this.getRemainingToPay();
        if (remaining > 0.001) {
            alert(`Ainda resta um saldo de R$ ${remaining.toFixed(2)} a ser pago.`);
            return;
        }

        const temCrediario = this.payments.some(p => p.forma === 'CREDIARIO');
        let clienteId = null;

        const cliSelect = document.getElementById('modal-cliente-select') || document.getElementById('cliente-select');
        if (cliSelect && cliSelect.value) {
            clienteId = parseInt(cliSelect.value, 10);
        }

        if (temCrediario && !clienteId) {
            alert('Vendas contendo parcelas no Crediário / Fiado exigem a seleção de um Cliente.');
            if (cliSelect) cliSelect.focus();
            return;
        }

        this.isProcessingSale = true;
        const btnConfirm = document.getElementById('btn-efetivar-confirmacao');
        if (btnConfirm) {
            btnConfirm.disabled = true;
            btnConfirm.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Processando...';
        }

        const offlineUuid = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : ('OFF-' + Date.now() + '-' + Math.random().toString(36).substring(2, 9));

        const debtItem = this.cart.find(i => i.tipo_item === 'RECEBIMENTO_DIVIDA');
        const prodItems = this.cart.filter(i => i.tipo_item !== 'RECEBIMENTO_DIVIDA');

        const vendaPayload = {
            offline_uuid: offlineUuid,
            cliente_id: clienteId,
            desconto: parseFloat(this.getDiscountAmount().toFixed(2)),
            itens: prodItems.map(i => ({
                produto_id: i.produto_id,
                quantidade: parseFloat(i.quantidade),
                preco_venda: parseFloat(i.preco_venda.toFixed(2))
            })),
            recebimento_divida: debtItem ? {
                cliente_id: debtItem.cliente_id,
                valor_pago: parseFloat(debtItem.valor_pago.toFixed(2)),
                valor_abatimento: parseFloat(debtItem.valor_abatimento.toFixed(2)),
                motivo_abatimento: debtItem.motivo_abatimento || ''
            } : null,
            pagamentos: this.payments.map(p => ({
                forma: p.forma,
                valor: parseFloat(p.valor.toFixed(2)),
                troco: parseFloat(p.troco.toFixed(2)),
                dados: {}
            })),
            total: parseFloat(this.getTotal().toFixed(2))
        };

        try {
            if (window.pdvOfflineDB) {
                await window.pdvOfflineDB.enfileirarVenda(vendaPayload);
                this.updateNetworkBadge();
            }

            if (this.isOnline) {
                try {
                    const response = await fetch('/api/v1/vendas/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.getCsrfToken()
                        },
                        body: JSON.stringify(vendaPayload)
                    });

                    if (response.ok) {
                        const data = await response.json();
                        if (window.pdvOfflineDB) {
                            await window.pdvOfflineDB.atualizarStatusVenda(offlineUuid, 'SINCRONIZADA', null, data);
                            this.updateNetworkBadge();
                        }
                        this.closeModals();

                        if (data.codigo_venda) {
                            if (confirm(`Venda #${data.codigo_venda} finalizada com SUCESSO!\n\nDeseja imprimir o comprovante da venda?`)) {
                                this.abrirRecibo(data.id);
                            }
                        } else {
                            alert(`Recebimento de Dívida finalizado com SUCESSO!\n\nCliente: ${data.cliente}\nValor Recebido: R$ ${data.valor_pago.toFixed(2)}\nTotal Liquidado: R$ ${data.total_liquidado.toFixed(2)}\nSaldo Restante: R$ ${data.saldo_devedor_restante.toFixed(2)}`);
                        }
                        this.clearCart();
                        return;
                    } else {
                        const errorData = await response.json();
                        const errorMsg = errorData.error || JSON.stringify(errorData);
                        if (window.pdvOfflineDB) {
                            await window.pdvOfflineDB.atualizarStatusVenda(offlineUuid, 'ERRO_PERMANENTE', errorMsg);
                            this.updateNetworkBadge();
                        }
                        alert(`Atenção: A venda não pôde ser aprovada pelo servidor:\n\n${errorMsg}`);
                        return;
                    }
                } catch (networkErr) {
                    console.warn('[PDV] Falha de comunicação na finalização. Operação gravada em fila offline:', networkErr);
                    this.isOnline = false;
                    this.updateNetworkBadge();
                }
            }

            this.closeModals();
            alert('Venda gravada localmente com sucesso no terminal (Modo Offline)!\n\nA sincronização será realizada automaticamente assim que a conexão com o servidor for restabelecida.');
            this.clearCart();
        } catch (err) {
            console.error('[PDV] Erro crítico ao processar venda:', err);
            alert(`Erro ao gravar operação: ${err.message || err}`);
        } finally {
            this.isProcessingSale = false;
            if (btnConfirm) {
                btnConfirm.disabled = false;
                btnConfirm.innerHTML = '<i class="bi bi-check2-all me-1"></i> CONFIRMAR VENDA';
            }
        }
    }

    abrirRecibo(vendaId) {
        if (!vendaId) return;
        const printWindow = window.open(`/vendas/recibo/${vendaId}/`, '_blank', 'width=450,height=650');
        if (printWindow) {
            printWindow.focus();
        }
    }

    async sincronizarVendasOffline() {
        if (this.isSyncing || !window.pdvOfflineDB) return;
        const pendentes = await window.pdvOfflineDB.getVendasPendentes();
        if (!pendentes || pendentes.length === 0) {
            this.updateNetworkBadge();
            return;
        }

        this.isSyncing = true;
        this.updateNetworkBadge();

        try {
            const payloadVendas = pendentes.map(p => ({
                offline_uuid: p.offline_uuid,
                cliente_id: p.payload.cliente_id,
                desconto: p.payload.desconto,
                itens: p.payload.itens,
                pagamentos: p.payload.pagamentos,
                observacao: p.payload.observacao
            }));

            const response = await fetch('/api/v1/pdv/sync/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({ vendas: payloadVendas })
            });

            if (response.ok) {
                const res = await response.json();

                if (res.vendas && Array.isArray(res.vendas)) {
                    for (const v of res.vendas) {
                        if (v.offline_uuid) {
                            await window.pdvOfflineDB.atualizarStatusVenda(v.offline_uuid, 'SINCRONIZADA', null, v);
                        }
                    }
                }

                if (res.erros && Array.isArray(res.erros)) {
                    for (const err of res.erros) {
                        if (err.offline_uuid) {
                            await window.pdvOfflineDB.atualizarStatusVenda(err.offline_uuid, 'ERRO_PERMANENTE', err.error || JSON.stringify(err.erros));
                        }
                    }
                }

                console.log(`[PDV Sync] Sincronização concluída: ${res.total_sincronizadas} sucesso(s), ${res.erros?.length || 0} erro(s).`);
            }
        } catch (e) {
            console.error('[PDV Sync] Falha durante sincronização da fila:', e);
        } finally {
            this.isSyncing = false;
            this.updateNetworkBadge();
        }
    }

    getCsrfToken() {
        const input = document.querySelector('[name=csrfmiddlewaretoken]');
        if (input) return input.value;
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1];
        return cookieValue || '';
    }
}

// Inicialização Global
document.addEventListener('DOMContentLoaded', () => {
    window.pdvApp = new PDVApp();
});
