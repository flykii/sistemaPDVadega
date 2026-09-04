import calendar
from datetime import date, timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import (
    ContaReceber, ContaPagar, FluxoCaixa, PagamentoContaReceber,
    CategoriaDespesa, DespesaRecorrente, PagamentoContaPagar
)
from apps.clientes.models import Cliente
from apps.caixas.models import SessaoCaixa, MovimentacaoCaixa
from apps.core.models import AuditService


class FinancialService:
    # =========================================================================
    # CONTAS A RECEBER / CREDIÁRIO
    # =========================================================================
    @staticmethod
    @transaction.atomic
    def receber_pagamento_conta(
        conta: ContaReceber,
        valor_pago: Decimal | float,
        forma_pagamento: str = 'DINHEIRO',
        troco: Decimal | float = Decimal('0.00'),
        sessao_caixa = None,
        usuario = None,
        observacao: str = ''
    ) -> PagamentoContaReceber:
        val_pago_dec = Decimal(str(valor_pago)).quantize(Decimal('0.01'))
        troco_dec = Decimal(str(troco)).quantize(Decimal('0.01'))

        if val_pago_dec <= Decimal('0.00'):
            raise ValueError("O valor de pagamento deve ser estritamente maior que zero.")

        if troco_dec < Decimal('0.00'):
            raise ValueError("O valor do troco não pode ser negativo.")

        if forma_pagamento != 'DINHEIRO' and troco_dec > Decimal('0.00'):
            raise ValueError("Troco só é permitido para pagamentos em DINHEIRO.")

        valor_efetivo = val_pago_dec - troco_dec
        if valor_efetivo <= Decimal('0.00'):
            raise ValueError("O valor efetivo destinado à quitação deve ser maior que zero.")

        # Bloqueio transacional da Conta a Receber
        conta_db = ContaReceber.objects.select_for_update().get(id=conta.id)

        if conta_db.status in ['QUITADA', 'PAGO']:
            raise ValueError("Esta conta a receber já está totalmente quitada.")

        if conta_db.status == 'CANCELADA':
            raise ValueError("Não é possível receber pagamentos de uma conta cancelada.")

        saldo_pendente = conta_db.saldo
        if valor_efetivo > saldo_pendente:
            raise ValueError(
                f"O valor efetivo recebido (R$ {valor_efetivo:.2f}) não pode ser maior que o saldo da dívida (R$ {saldo_pendente:.2f})."
            )

        pagamento = PagamentoContaReceber.objects.create(
            empresa=conta_db.empresa,
            conta_receber=conta_db,
            valor=val_pago_dec,
            troco=troco_dec,
            forma_pagamento=forma_pagamento,
            sessao_caixa=sessao_caixa,
            usuario=usuario,
            observacao=observacao.strip()
        )

        conta_db.valor_pago += valor_efetivo
        if conta_db.saldo <= Decimal('0.00'):
            conta_db.status = 'QUITADA'
            conta_db.data_pagamento = timezone.now().date()
        else:
            conta_db.status = 'PARCIAL'
        conta_db.save()

        # Atualiza o saldo devedor do Cliente com bloqueio de linha
        if conta_db.cliente_id:
            cliente_db = Cliente.objects.select_for_update().get(id=conta_db.cliente_id)
            cliente_db.saldo_devedor = max(Decimal('0.00'), cliente_db.saldo_devedor - valor_efetivo)
            cliente_db.save()

        # Integração com Caixa Físico (Apenas DINHEIRO aumenta a gaveta)
        if forma_pagamento == 'DINHEIRO' and sessao_caixa:
            MovimentacaoCaixa.objects.create(
                empresa=conta_db.empresa,
                sessao_caixa=sessao_caixa,
                tipo='SUPRIMENTO',
                valor=valor_efetivo,
                motivo=f"Recebimento Dívida #{conta_db.id} - {conta_db.cliente.nome if conta_db.cliente else 'Cliente'}",
                operador=usuario
            )

        # Lança no Fluxo de Caixa Geral
        FluxoCaixa.objects.create(
            empresa=conta_db.empresa,
            tipo='ENTRADA',
            categoria='Recebimento Crediário',
            descricao=f"Recebimento Dívida #{conta_db.id} ({forma_pagamento}) - {conta_db.cliente.nome if conta_db.cliente else 'Cliente'}",
            valor=valor_efetivo,
            referencia_origem=f"RECEBER-{conta_db.id}"
        )

        # Trilha de Auditoria do Recebimento
        AuditService.registrar(
            empresa=conta_db.empresa,
            usuario=usuario,
            acao='RECEBIMENTO_REGISTRADO',
            entidade='ContaReceber',
            entidade_id=conta_db.id,
            descricao=f"Recebimento de R$ {valor_efetivo:.2f} ({forma_pagamento}) para a conta #{conta_db.id} ({conta_db.cliente.nome if conta_db.cliente else 'Cliente'})",
            dados_posteriores={
                'valor_recebido': str(valor_efetivo),
                'forma_pagamento': forma_pagamento,
                'saldo_restante_conta': str(conta_db.saldo),
                'status_conta': conta_db.status
            }
        )

        return pagamento

    @staticmethod
    @transaction.atomic
    def baixar_conta_receber(conta: ContaReceber, data_pagamento=None, usuario=None, sessao_caixa=None) -> ContaReceber:
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=conta.saldo,
            forma_pagamento='DINHEIRO',
            troco=Decimal('0.00'),
            sessao_caixa=sessao_caixa,
            usuario=usuario,
            observacao="Quitação integral avulsa"
        )
        conta.refresh_from_db()
        return conta

    @staticmethod
    @transaction.atomic
    def cancelar_conta_receber(conta: ContaReceber, usuario=None, motivo: str = '') -> ContaReceber:
        conta_db = ContaReceber.objects.select_for_update().get(id=conta.id)

        if conta_db.status == 'CANCELADA':
            raise ValueError("Esta conta a receber já se encontra cancelada.")

        if conta_db.valor_pago > Decimal('0.00'):
            raise ValueError("Não é possível cancelar uma conta a receber que já possui recebimentos amortizados.")

        # Abate do saldo devedor do cliente
        if conta_db.cliente_id:
            cliente_db = Cliente.objects.select_for_update().get(id=conta_db.cliente_id)
            cliente_db.saldo_devedor = max(Decimal('0.00'), cliente_db.saldo_devedor - conta_db.saldo)
            cliente_db.save()

        conta_db.status = 'CANCELADA'
        if motivo:
            conta_db.observacoes = f"{conta_db.observacoes}\n[Cancelamento em {timezone.now().strftime('%d/%m/%Y %H:%M')}]: {motivo}".strip()
        conta_db.save()

        AuditService.registrar(
            empresa=conta_db.empresa,
            usuario=usuario,
            acao='RECEBIMENTO_CANCELADO',
            entidade='ContaReceber',
            entidade_id=conta_db.id,
            descricao=f"Conta a receber #{conta_db.id} de R$ {conta_db.valor} cancelada. Motivo: {motivo}",
            motivo=motivo,
            dados_posteriores={'status': 'CANCELADA'}
        )

        return conta_db

    # =========================================================================
    # DESPESAS AVULSAS E CONTAS A PAGAR
    # =========================================================================
    @staticmethod
    @transaction.atomic
    def cadastrar_despesa_avulsa(
        empresa,
        descricao: str,
        valor: Decimal | float,
        categoria: CategoriaDespesa = None,
        fornecedor = None,
        data_vencimento = None,
        data_competencia = None,
        forma_pagamento: str = '',
        pago_imediatamente: bool = False,
        sessao_caixa = None,
        usuario = None,
        observacoes: str = ''
    ) -> ContaPagar:
        val_dec = Decimal(str(valor)).quantize(Decimal('0.01'))
        if val_dec <= Decimal('0.00'):
            raise ValueError("O valor da despesa deve ser estritamente maior que zero.")

        dt_comp = data_competencia or timezone.now().date()
        dt_venc = data_vencimento or dt_comp

        conta = ContaPagar.objects.create(
            empresa=empresa,
            descricao=descricao.strip(),
            categoria=categoria,
            fornecedor=fornecedor,
            valor=val_dec,
            valor_original=val_dec,
            valor_pago=Decimal('0.00'),
            data_competencia=dt_comp,
            data_vencimento=dt_venc,
            forma_pagamento=forma_pagamento,
            usuario=usuario,
            sessao_caixa=sessao_caixa if pago_imediatamente else None,
            status='ABERTA',
            observacoes=observacoes.strip()
        )

        if pago_imediatamente:
            FinancialService.pagar_conta_despesa(
                conta=conta,
                valor_pago=val_dec,
                forma_pagamento=forma_pagamento or 'DINHEIRO',
                sessao_caixa=sessao_caixa,
                usuario=usuario,
                observacao="Pagamento no ato do lançamento"
            )
            conta.refresh_from_db()

        return conta

    # =========================================================================
    # DESPESAS RECORRENTES & PREVISÕES MENSAIS
    # =========================================================================
    @staticmethod
    @transaction.atomic
    def gerar_previsoes_despesas_recorrentes(empresa, mes: int, ano: int, usuario = None) -> list[ContaPagar]:
        """Gera as ocorrências mensais de despesas fixas sem duplicidade."""
        competencia = f"{ano:04d}-{mes:02d}"
        recorrentes = DespesaRecorrente.objects.filter(empresa=empresa, ativo=True)
        
        _, ultimo_dia = calendar.monthrange(ano, mes)
        primeiro_dia_mes = date(ano, mes, 1)
        ultimo_dia_mes = date(ano, mes, ultimo_dia)

        geradas = []

        for rec in recorrentes:
            # Verifica se o período de vigência abrange este mês
            if rec.data_inicio > ultimo_dia_mes:
                continue
            if rec.data_fim and rec.data_fim < primeiro_dia_mes:
                continue

            # Previne duplicidade de geração da mesma competência
            ja_existe = ContaPagar.objects.filter(
                empresa=empresa,
                despesa_recorrente=rec,
                recorrente_competencia=competencia
            ).exists()

            if ja_existe:
                continue

            dia_venc = min(rec.dia_vencimento, ultimo_dia)
            data_venc = date(ano, mes, dia_venc)

            conta = ContaPagar.objects.create(
                empresa=empresa,
                despesa_recorrente=rec,
                recorrente_competencia=competencia,
                categoria=rec.categoria,
                fornecedor=rec.fornecedor,
                descricao=f"{rec.descricao} ({mes:02d}/{ano})",
                valor=rec.valor_estimado,
                valor_original=rec.valor_estimado,
                valor_pago=Decimal('0.00'),
                data_competencia=primeiro_dia_mes,
                data_vencimento=data_venc,
                usuario=usuario,
                status='ABERTA',
                observacoes=rec.observacoes
            )
            geradas.append(conta)

        return geradas

    # =========================================================================
    # PAGAMENTO / BAIXA DE DESPESAS (COM INTEGRAÇÃO AO CAIXA)
    # =========================================================================
    @staticmethod
    @transaction.atomic
    def pagar_conta_despesa(
        conta: ContaPagar,
        valor_pago: Decimal | float,
        forma_pagamento: str = 'DINHEIRO',
        sessao_caixa = None,
        usuario = None,
        observacao: str = ''
    ) -> PagamentoContaPagar:
        val_pago_dec = Decimal(str(valor_pago)).quantize(Decimal('0.01'))
        if val_pago_dec <= Decimal('0.00'):
            raise ValueError("O valor de pagamento deve ser maior que zero.")

        # Bloqueio transacional de concorrência
        conta_db = ContaPagar.objects.select_for_update().get(id=conta.id)

        if conta_db.status in ['PAGA', 'PAGO']:
            raise ValueError("Esta despesa / conta a pagar já está totalmente quitada.")

        if conta_db.status == 'CANCELADA':
            raise ValueError("Não é possível realizar pagamentos de uma conta cancelada.")

        saldo_pendente = conta_db.saldo
        if val_pago_dec > saldo_pendente:
            raise ValueError(
                f"O valor pago (R$ {val_pago_dec:.2f}) não pode ser maior que o saldo restante da despesa (R$ {saldo_pendente:.2f})."
            )

        # Regra de Caixa Físico:
        # Se for pago em DINHEIRO e houver sessão de caixa informada:
        if forma_pagamento == 'DINHEIRO' and sessao_caixa:
            sessao_db = SessaoCaixa.objects.select_for_update().get(id=sessao_caixa.id)
            if sessao_db.status != 'ABERTA':
                raise ValueError("Não é possível realizar pagamentos de despesas pelo caixa em uma sessão já FECHADA.")

            if sessao_db.saldo_esperado < val_pago_dec:
                raise ValueError(
                    f"Saldo físico insuficiente na gaveta do caixa. Disponível: R$ {sessao_db.saldo_esperado:.2f}, Solicitado: R$ {val_pago_dec:.2f}."
                )

            # Registra a saída física do dinheiro na gaveta
            MovimentacaoCaixa.objects.create(
                empresa=conta_db.empresa,
                sessao_caixa=sessao_db,
                tipo='DESPESA',
                valor=val_pago_dec,
                motivo=f"Pagamento Despesa #{conta_db.id} - {conta_db.descricao}",
                operador=usuario
            )

        # Registra o pagamento detalhado
        pagamento = PagamentoContaPagar.objects.create(
            empresa=conta_db.empresa,
            conta_pagar=conta_db,
            valor=val_pago_dec,
            forma_pagamento=forma_pagamento,
            sessao_caixa=sessao_caixa,
            usuario=usuario,
            observacao=observacao.strip()
        )

        conta_db.valor_pago += val_pago_dec
        conta_db.forma_pagamento = forma_pagamento
        conta_db.sessao_caixa = sessao_caixa

        if conta_db.saldo <= Decimal('0.00'):
            conta_db.status = 'PAGA'
            conta_db.data_pagamento = timezone.now().date()
        else:
            conta_db.status = 'PARCIAL'

        conta_db.save()

        # Lança a saída no Fluxo de Caixa Geral
        cat_nome = conta_db.categoria.nome if conta_db.categoria else "Despesas Gerais"
        FluxoCaixa.objects.create(
            empresa=conta_db.empresa,
            tipo='SAIDA',
            categoria=f"Despesa: {cat_nome}",
            descricao=f"Pagamento Despesa #{conta_db.id} ({forma_pagamento}) - {conta_db.descricao}",
            valor=val_pago_dec,
            referencia_origem=f"DESPESA-{conta_db.id}"
        )

        return pagamento

    @staticmethod
    @transaction.atomic
    def cancelar_conta_despesa(conta: ContaPagar, usuario = None, motivo: str = '') -> ContaPagar:
        conta_db = ContaPagar.objects.select_for_update().get(id=conta.id)

        if conta_db.valor_pago > Decimal('0.00'):
            raise ValueError("Não é possível cancelar uma despesa que já possui pagamentos ou amortizações parciais.")

        conta_db.status = 'CANCELADA'
        if motivo:
            conta_db.observacoes = f"{conta_db.observacoes}\n[Cancelamento em {timezone.now().strftime('%d/%m/%Y %H:%M')}]: {motivo}".strip()
        conta_db.save()
        return conta_db

    @staticmethod
    @transaction.atomic
    def baixar_conta_pagar(conta: ContaPagar, data_pagamento=None, usuario=None, sessao_caixa=None) -> ContaPagar:
        """Compatibilidade para quitação direta integral."""
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=conta.saldo,
            forma_pagamento='DINHEIRO',
            sessao_caixa=sessao_caixa,
            usuario=usuario,
            observacao="Quitação integral avulsa"
        )
        conta.refresh_from_db()
        return conta
