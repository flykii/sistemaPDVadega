from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.financeiro.models import FluxoCaixa

class CashService:
    @staticmethod
    @transaction.atomic
    def abrir_caixa(caixa: Caixa, operador, saldo_inicial: Decimal | float, nome_operador: str = '') -> SessaoCaixa:
        saldo = Decimal(str(saldo_inicial)).quantize(Decimal('0.01'))
        if saldo < Decimal('0.00'):
            raise ValueError("O saldo inicial não pode ser negativo.")

        # Lock do caixa
        cx = Caixa.objects.select_for_update().get(id=caixa.id)

        # Verifica se já existe sessão aberta para o caixa
        sessao_aberta = SessaoCaixa.objects.filter(caixa=cx, status='ABERTA').first()
        if sessao_aberta:
            raise ValueError(f"O caixa '{cx.nome}' já possui uma sessão aberta (Sessão #{sessao_aberta.id}).")

        cx.status = 'ABERTO'
        cx.save()

        sessao = SessaoCaixa.objects.create(
            empresa=cx.empresa,
            caixa=cx,
            operador=operador,
            nome_operador=nome_operador.strip(),
            saldo_inicial=saldo,
            status='ABERTA'
        )
        return sessao

    @staticmethod
    def validar_sessao_dia_operacional(sessao: SessaoCaixa):
        """
        Verifica se a sessão informada foi aberta no dia operacional de hoje.
        Se pertencer a um dia anterior, impede novas operações financeiras/vendas antes do fechamento.
        """
        if not sessao or sessao.status != 'ABERTA':
            return
        from apps.core.operational_day import get_operational_date, get_operational_today
        dia_abertura = get_operational_date(sessao.data_abertura)
        dia_hoje = get_operational_today()
        if dia_abertura < dia_hoje:
            raise ValueError(
                f"O caixa '{sessao.caixa.nome}' (Sessão #{sessao.id}) foi aberto no dia operacional {dia_abertura.strftime('%d/%m/%Y')} e precisa ser fechado antes de realizar novas operações no dia de hoje ({dia_hoje.strftime('%d/%m/%Y')})."
            )

    @staticmethod
    @transaction.atomic
    def registrar_movimentacao(sessao: SessaoCaixa, tipo: str, valor: Decimal | float, motivo: str, operador) -> MovimentacaoCaixa:
        val = Decimal(str(valor)).quantize(Decimal('0.01'))
        if val <= Decimal('0.00'):
            raise ValueError("O valor da movimentação deve ser estritamente maior que zero.")

        sessao_db = SessaoCaixa.objects.select_for_update().get(id=sessao.id)
        if sessao_db.status != 'ABERTA':
            raise ValueError("Não é possível registrar movimentações operacionais em um caixa fechado.")

        CashService.validar_sessao_dia_operacional(sessao_db)

        tipo = tipo.upper().strip()
        if tipo not in ['SUPRIMENTO', 'SANGRIA', 'DESPESA', 'ESTORNO']:
            raise ValueError(f"Tipo de movimentação '{tipo}' inválido.")

        # Validação de saldo disponível para saídas (Sangria e Despesa)
        if tipo in ['SANGRIA', 'DESPESA']:
            saldo_disponivel = sessao_db.saldo_atual
            if val > saldo_disponivel:
                raise ValueError(f"Saldo insuficiente na gaveta para realizar esta retirada. Saldo disponível: R$ {saldo_disponivel:.2f}, Solicitado: R$ {val:.2f}.")

        mov = MovimentacaoCaixa.objects.create(
            empresa=sessao_db.empresa,
            sessao_caixa=sessao_db,
            tipo=tipo,
            valor=val,
            motivo=motivo.strip() or f"{tipo.title()} de Caixa",
            operador=operador
        )

        # Integração automática com o Fluxo de Caixa Financeiro
        if tipo == 'DESPESA':
            FluxoCaixa.objects.create(
                empresa=sessao_db.empresa,
                tipo='SAIDA',
                categoria='Despesa Caixa',
                descricao=f"Despesa paga pelo Caixa #{sessao_db.caixa.nome}: {mov.motivo}",
                valor=val,
                referencia_origem=f"CX-{sessao_db.id}-MOV-{mov.id}"
            )
        elif tipo == 'SANGRIA':
            FluxoCaixa.objects.create(
                empresa=sessao_db.empresa,
                tipo='SAIDA',
                categoria='Sangria',
                descricao=f"Sangria Caixa #{sessao_db.caixa.nome}: {mov.motivo}",
                valor=val,
                referencia_origem=f"CX-{sessao_db.id}-MOV-{mov.id}"
            )
        elif tipo == 'SUPRIMENTO':
            FluxoCaixa.objects.create(
                empresa=sessao_db.empresa,
                tipo='ENTRADA',
                categoria='Suprimento Caixa',
                descricao=f"Aporte Suprimento Caixa #{sessao_db.caixa.nome}: {mov.motivo}",
                valor=val,
                referencia_origem=f"CX-{sessao_db.id}-MOV-{mov.id}"
            )

        return mov

    @staticmethod
    @transaction.atomic
    def fechar_caixa(sessao: SessaoCaixa, saldo_final_informado: Decimal | float, observacoes: str = '') -> SessaoCaixa:
        sessao_db = SessaoCaixa.objects.select_for_update().get(id=sessao.id)
        if sessao_db.status == 'FECHADA':
            raise ValueError("Esta sessão de caixa já se encontra fechada.")

        informado = Decimal(str(saldo_final_informado)).quantize(Decimal('0.01'))
        saldo_calculado = sessao_db.saldo_esperado
        diferenca = informado - saldo_calculado

        sessao_db.saldo_final_calculado = saldo_calculado
        sessao_db.saldo_final_informado = informado
        sessao_db.diferenca = diferenca
        sessao_db.data_fechamento = timezone.now()
        sessao_db.status = 'FECHADA'
        sessao_db.observacoes = observacoes.strip()
        sessao_db.save()

        sessao_db.caixa.status = 'FECHADO'
        sessao_db.caixa.save()

        # Atualiza a instância em memória caso tenha sido passada por referência
        sessao.status = 'FECHADA'
        sessao.saldo_final_calculado = saldo_calculado
        sessao.saldo_final_informado = informado
        sessao.diferenca = diferenca
        sessao.data_fechamento = sessao_db.data_fechamento
        sessao.observacoes = sessao_db.observacoes

        return sessao_db
