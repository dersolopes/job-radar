import json

import requests

from core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database.database import definir_feedback, definir_metadado, obter_metadado
from core.logger import get_logger

logger = get_logger()


def enviar_mensagem(texto: str, reply_markup: dict | None = None) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram não configurado (token/chat_id ausentes no .env). Pulando envio.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "disable_web_page_preview": False,
    }
    # Telegram exige reply_markup como string JSON quando o corpo do POST é
    # form-encoded (o `data=` abaixo) — passar o dict cru falha silenciosamente
    # (o teclado não aparece, sem erro nenhum reportado pela API).
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)

    try:
        resposta = requests.post(url, data=payload, timeout=10)
        resposta.raise_for_status()
        return True
    # MEDIDO: logar a exceção direta (`{e}`) põe a URL inteira no log —
    # `url` tem o token embutido (bot{TOKEN}/sendMessage), e a mensagem
    # padrão de erro de conexão do requests/urllib3 (ProxyError,
    # ConnectionError...) inclui a URL completa que falhou. 6 ocorrências
    # reais em jobradar.log confirmaram o vazamento: arquivo é gitignored
    # (não vai pro repo) mas existe em disco e o GitHub Actions manda a
    # mesma mensagem pro stdout do job, visível em log de execução. HTTPError
    # (erro de resposta, ex: 401/403 do próprio Telegram) tem `.response`
    # com status e motivo, sem token nenhum — loga isso. Qualquer outra
    # RequestException (falha de conexão, nunca chegou a ter resposta) loga
    # só o tipo da exceção — nunca `str(e)`, nunca `url`.
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        motivo = e.response.reason if e.response is not None else "sem detalhe"
        logger.error(f"Erro ao enviar mensagem no Telegram: HTTP {status} ({motivo})")
        return False
    except requests.RequestException as e:
        logger.error(
            f"Erro ao enviar mensagem no Telegram: {type(e).__name__} "
            "(falha de conexão, sem resposta do servidor)"
        )
        return False


def _linha_relevancia(pontos: int) -> str:
    """Renderiza Job.relevancia (0-10, ver pontuar_relevancia em job.py) como
    estrelas — 10 pontos vira 5 estrelas, arredondado (6/10 vira 3, não 2.5).
    Não é filtro, só destaque visual pra priorizar leitura entre as vagas
    aprovadas do ciclo (item 07 da auditoria: com ~320 vaga/dia, tudo
    chegava com o mesmo destaque)."""
    # (pontos + 1) // 2 em vez de round(pontos / 2): round() do Python
    # arredonda .5 pro par mais próximo (5/10 vira 2 estrelas, 7/10 vira 4)
    # — inconsistente e contraintuitivo pra quem só olha o emoji. Assim
    # sempre arredonda .5 pra cima (5/10 = 3, 7/10 = 4, sempre igual).
    cheias = (pontos + 1) // 2
    return "⭐" * cheias + "☆" * (5 - cheias) + f" ({pontos}/10)"


def _teclado_feedback(job_id: str) -> dict:
    """Teclado inline 👍/👎 anexado à notificação — callback_data carrega a
    direção (1/0) e o id do Job (hash md5, 32 chars), separados por "|".
    Formato curto de propósito: o limite real do Telegram pra callback_data
    é 64 bytes, e "fb|1|" + hash já usa 37 — sobra margem, mas não dá pra
    ser generoso (ex: guardar o link inteiro não caberia).

    Sem ISSO gravado no botão, o callback_query que chega quando alguém
    aperta não tem como saber DE QUAL vaga — a mensagem em si não é
    suficiente (ver processar_feedback_pendente)."""
    return {
        "inline_keyboard": [[
            {"text": "👍", "callback_data": f"fb|1|{job_id}"},
            {"text": "👎", "callback_data": f"fb|0|{job_id}"},
        ]]
    }


def _linha_aviso_antiga(job) -> str:
    """Aviso quando Job.publicacao_antiga é True (publicado_em bate "há X
    meses/anos") — a vaga ainda passou no filtro e está sendo notificada
    (ver main.py: só muda pra digest em vez de imediata, nunca é
    descartada — "duplicar/mostrar é aceitável, perder não" é o mesmo
    princípio do digest), mas sem essa linha a mensagem parece uma vaga
    fresca igual a qualquer outra, quando na real pode já estar
    preenchida há tempos."""
    if not job.publicacao_antiga:
        return ""
    return f"⚠️ Postada {job.publicado_em_legivel} — pode já estar preenchida.\n"


def notificar_vaga(job) -> bool:
    # TODO (Fase 3): incluir aqui a % de compatibilidade com o currículo,
    # calculada por IA, quando essa etapa for implementada.
    #
    # Linha de publicação só aparece quando a fonte expõe isso (nem toda
    # expõe — ver Job.publicado_em / extrair_data_publicacao em job.py).
    linha_publicacao = f"Publicada: {job.publicado_em_legivel}\n" if job.publicado_em else ""
    linha_modalidade = f"Modalidade: {job.modalidade}\n" if job.modalidade else ""
    texto = (
        f"🚨 Nova vaga encontrada!\n\n"
        f"{_linha_aviso_antiga(job)}"
        f"Relevância: {_linha_relevancia(job.relevancia)}\n"
        f"Motivo: {job.motivo}\n"
        f"Empresa: {job.empresa}\n"
        f"Cargo: {job.titulo}\n"
        f"Nível: {job.senioridade}\n"
        f"Local: {job.local}\n"
        f"{linha_modalidade}"
        f"Site: {job.site}\n"
        f"{linha_publicacao}\n"
        f"Encontrada agora\n\n"
        f"Link:\n{job.link}"
    )
    return enviar_mensagem(texto, reply_markup=_teclado_feedback(job.id))


def notificar_vaga_exploratoria(job) -> bool:
    """Vaga achada via eixo Ibérico (Portugal/Espanha) — fisicamente lá, não
    remota. Mensagem separada de notificar_vaga() de propósito: mandar isso
    pelo template normal sugeriria "achado remoto de verdade", quando na
    real é presencial/híbrida encontrada por busca geográfica dedicada (ver
    CIDADES_EUROPA_IBERICA em config.py/config_intl.py). Compartilhada pelos
    dois pipelines que têm esse eixo (main.py e main_intl.py) — texto já era
    genérico o bastante pros dois antes de virar função só de um deles,
    então movida pra cá em vez de duplicada.
    """
    linha_modalidade = f"Modalidade: {job.modalidade}\n" if job.modalidade else ""
    texto = (
        f"🧭 Vaga exploratória (Portugal/Espanha)\n\n"
        f"{_linha_aviso_antiga(job)}"
        f"Relevância: {_linha_relevancia(job.relevancia)}\n"
        f"Motivo: {job.motivo}\n"
        f"Empresa: {job.empresa}\n"
        f"Cargo: {job.titulo}\n"
        f"Nível: {job.senioridade}\n"
        f"Local: {job.local}\n"
        f"{linha_modalidade}"
        f"Site: {job.site}\n\n"
        f"Achada via busca por Portugal/Espanha — modalidade não confirmada "
        f"como remota, pode ser presencial ou híbrida. Confirma no link.\n\n"
        f"Link:\n{job.link}"
    )
    return enviar_mensagem(texto, reply_markup=_teclado_feedback(job.id))


# Margem sob o limite real do Telegram (4096 caracteres por mensagem) —
# sobra pra cabeçalho/rodapé e pra emoji/acentuação que ocupam mais de 1
# "caractere" em contagem de bytes.
_LIMITE_CHARS_DIGEST = 3500


def montar_digest(vagas: list[tuple], rotulo_perfil: str) -> list[str]:
    """Monta o texto do digest diário (item 08) a partir do que
    obter_vagas_pendentes_digest() devolve — já vem ordenado da mais
    relevante pra menos. Devolve uma LISTA de mensagens, não uma só: com
    ~93% do volume indo pro digest (ver LIMIAR_DIGEST_IMEDIATO em
    config.py), um dia cheio passa fácil dos 4096 caracteres do Telegram
    — quebra em partes numeradas em vez de estourar/truncar."""
    linhas = [
        f'{"🧭" if exploratoria else "•"} {_linha_relevancia(relevancia or 0)} '
        f'{titulo} — {empresa}\n{link}'
        for titulo, empresa, link, relevancia, exploratoria in vagas
    ]

    partes: list[list[str]] = []
    parte_atual: list[str] = []
    tamanho_atual = 0
    for linha in linhas:
        if parte_atual and tamanho_atual + len(linha) + 1 > _LIMITE_CHARS_DIGEST:
            partes.append(parte_atual)
            parte_atual, tamanho_atual = [], 0
        parte_atual.append(linha)
        tamanho_atual += len(linha) + 1
    if parte_atual:
        partes.append(parte_atual)

    total_partes = len(partes)
    mensagens = []
    for i, parte in enumerate(partes, start=1):
        cabecalho = f"📋 Digest diário — {rotulo_perfil} ({len(vagas)} vaga(s))"
        if total_partes > 1:
            cabecalho += f" — parte {i}/{total_partes}"
        mensagens.append(cabecalho + "\n\n" + "\n".join(parte))
    return mensagens


def enviar_digest(vagas: list[tuple], rotulo_perfil: str) -> bool:
    """Manda todas as partes do digest em sequência. Só True se TODAS
    confirmarem — ver marcar_digest_enviado em database.py: o chamador só
    limpa a fila com esse retorno True, então falha parcial mantém tudo
    pendente (inclusive parte já enviada com sucesso) pro próximo envio.
    Preferir duplicar uma parte a perder vaga que nunca chegou a notificar."""
    if not vagas:
        return True
    return all(enviar_mensagem(mensagem) for mensagem in montar_digest(vagas, rotulo_perfil))


def _chamar_api_telegram(metodo: str, payload: dict) -> dict | None:
    """POST genérico pra método da Bot API além de sendMessage — usado só
    pelo fluxo de feedback (getUpdates/answerCallbackQuery/
    editMessageReplyMarkup). Mesmo tratamento de erro de enviar_mensagem
    (nunca loga token nem URL — ver comentário lá), sem duplicar o bloco
    try/except em cada método novo."""
    if not TELEGRAM_BOT_TOKEN:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{metodo}"
    try:
        resposta = requests.post(url, data=payload, timeout=10)
        resposta.raise_for_status()
        return resposta.json()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        motivo = e.response.reason if e.response is not None else "sem detalhe"
        logger.error(f"Erro ao chamar Telegram {metodo}: HTTP {status} ({motivo})")
        return None
    except requests.RequestException as e:
        logger.error(
            f"Erro ao chamar Telegram {metodo}: {type(e).__name__} "
            "(falha de conexão, sem resposta do servidor)"
        )
        return None


def _parsear_callback_data(data: str) -> tuple[str, str] | None:
    """Extrai (job_id, feedback) de um callback_data no formato
    'fb|1|<id>' (positivo) / 'fb|0|<id>' (negativo) — None quando não
    reconhece o formato (ex: o botão de confirmação 'fb|ok|-' que substitui
    o teclado original depois de registrado, ou qualquer callback_data que
    não seja deste projeto). Função pura, separada da chamada de rede de
    propósito — é a parte que vale a pena testar sem mockar HTTP."""
    partes = (data or "").split("|")
    if len(partes) != 3 or partes[0] != "fb" or partes[1] not in ("1", "0"):
        return None
    return partes[2], ("positivo" if partes[1] == "1" else "negativo")


_OFFSET_CHAVE = "telegram_update_offset"


def processar_feedback_pendente():
    """Consome os cliques em 👍/👎 desde o último ciclo. Sem webhook, sem
    servidor próprio — o cron de 3 em 3 horas do projeto (ver
    .github/workflows/jobradar.yml) já FAZ o papel de polling: cada
    execução pergunta ao Telegram "o que mudou desde a última vez que eu
    perguntei" via getUpdates, processa, e segue pro ciclo de busca normal.
    Mesma filosofia de custo zero de infraestrutura do resto do projeto.

    offset fica salvo em metadados (mesma tabela chave/valor do heartbeat/
    digest/rodízio de termos): getUpdates com offset=N+1 confirma pro
    próprio Telegram que tudo até N já foi visto — sem isso, o mesmo
    clique seria reprocessado em todo ciclo daqui pra frente.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    payload = {
        "timeout": 0,  # short poll -- só pergunta "tem algo pendente agora", não fica esperando
        "limit": 100,
        "allowed_updates": json.dumps(["callback_query"]),
    }
    offset_salvo = obter_metadado(_OFFSET_CHAVE)
    if offset_salvo:
        payload["offset"] = str(int(offset_salvo) + 1)

    resultado = _chamar_api_telegram("getUpdates", payload)
    if resultado is None or not resultado.get("ok"):
        return

    updates = resultado.get("result", [])
    if not updates:
        return

    maior_update_id = None
    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None:
            maior_update_id = update_id if maior_update_id is None else max(maior_update_id, update_id)

        callback = update.get("callback_query")
        if not callback:
            continue

        # Só processa callback do chat configurado -- mesmo escopo de "bot
        # de uso pessoal, um chat só" que o resto do projeto assume.
        mensagem = callback.get("message") or {}
        chat_id = str((mensagem.get("chat") or {}).get("id", ""))
        if not chat_id or chat_id != str(TELEGRAM_CHAT_ID):
            continue

        parseado = _parsear_callback_data(callback.get("data", ""))
        if parseado is not None:
            job_id, feedback = parseado
            definir_feedback(job_id, feedback)
            emoji = "👍" if feedback == "positivo" else "👎"
            texto_toast = f"Registrado: {emoji}"
            # Substitui o teclado por um botão único, não-funcional de
            # propósito (callback_data "fb|ok|-" nunca bate no parser acima)
            # -- dá confirmação visual e evita clique duplicado mudando o
            # valor sem querer.
            novo_teclado = {"inline_keyboard": [[{"text": f"✅ Registrado: {emoji}", "callback_data": "fb|ok|-"}]]}
        else:
            texto_toast = "Já registrado."
            novo_teclado = None

        _chamar_api_telegram("answerCallbackQuery", {
            "callback_query_id": callback["id"],
            "text": texto_toast,
        })

        if novo_teclado is not None and mensagem.get("message_id"):
            _chamar_api_telegram("editMessageReplyMarkup", {
                "chat_id": chat_id,
                "message_id": mensagem["message_id"],
                "reply_markup": json.dumps(novo_teclado),
            })

    if maior_update_id is not None:
        definir_metadado(_OFFSET_CHAVE, str(maior_update_id))
