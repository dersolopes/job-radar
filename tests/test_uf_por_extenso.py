"""A guarda de UF tem que valer com o estado escrito por extenso.

MEDIDO (2026-08-21): a guarda só entendia SIGLA de duas letras. A mesma vaga
era barrada ou passava dependendo só de como a fonte escreve o local:

    "Campina Grande do Sul - PR"              -> barrada   (correto)
    "Campina Grande do Sul, Paraná, Brazil"   -> PASSAVA   (errado)

E o segundo formato é o do LinkedIn — hoje a origem de quase toda vaga
brasileira do projeto. A guarda estava furada exatamente onde mais importa.

Conferido contra os 38 formatos de local brasileiro que existem de verdade no
jobs.db: 36 resolvem UF. Os dois que não são "Brazil" puro (não declara estado
nenhum) e "Brasília, Federal District" — o LinkedIn escreve o DF em inglês.
"""

import pytest

from core.job import Job, _normalizar, _uf_declarada
from core.perfis import PERFIL_BR


def _vaga(local: str, modalidade: str = "Presencial") -> Job:
    return Job(
        titulo="Analista de Dados",
        empresa="Empresa",
        local=local,
        link="https://www.linkedin.com/jobs/view/" + local,
        site="LinkedIn",
        modalidade=modalidade,
    )


# Formatos REAIS extraidos do jobs.db, um por estado encontrado.
@pytest.mark.parametrize("local, uf", [
    ("Aracaju, Sergipe, Brazil", "se"),
    ("Belém, Pará, Brazil", "pa"),
    ("Belo Horizonte, Minas Gerais, Brazil", "mg"),
    ("Brasília, Federal District, Brazil", "df"),
    ("Curitiba, Paraná, Brazil", "pr"),
    ("Florianópolis, Santa Catarina, Brazil", "sc"),
    ("Fortaleza, Ceará, Brazil", "ce"),
    ("Goiânia, Goiás, Brazil", "go"),
    ("João Pessoa, Paraíba, Brazil", "pb"),
    ("Lajeado, Rio Grande do Sul, Brazil", "rs"),
    ("Maceió, Alagoas, Brazil", "al"),
    ("Manaus, Amazonas, Brazil", "am"),
    ("Natal, Rio Grande do Norte, Brazil", "rn"),
    ("Recife, Pernambuco, Brazil", "pe"),
    ("Salvador, Bahia, Brazil", "ba"),
    ("São Paulo, São Paulo, Brazil", "sp"),
    ("Vitória, Espírito Santo, Brazil", "es"),
])
def test_estado_por_extenso_vira_sigla(local, uf):
    assert _uf_declarada(_normalizar(local)) == uf


def test_sigla_continua_funcionando():
    """Regressão: o caminho antigo não pode ter sido trocado, só ampliado."""
    assert _uf_declarada(_normalizar("Natal - RN")) == "rn"
    assert _uf_declarada(_normalizar("Recife, PE")) == "pe"
    assert _uf_declarada(_normalizar("Manaus/AM")) == "am"


def test_local_sem_estado_continua_indefinido():
    """Sem estado declarado não há o que conferir — não pode virar palpite."""
    assert _uf_declarada(_normalizar("Brazil")) is None
    assert _uf_declarada(_normalizar("Recife")) is None
    assert _uf_declarada(_normalizar("Greater São Paulo Area")) is None


def test_homonima_com_estado_por_extenso_e_barrada():
    """O caso que passava: a cidade certa, no estado errado, escrito por extenso."""
    assert not _vaga("Campina Grande do Sul, Paraná, Brazil").combina_com(PERFIL_BR.regras)


def test_a_cidade_certa_continua_passando():
    """A outra metade: apertar a guarda não pode barrar a vaga de verdade."""
    for local in [
        "Campina Grande, Paraíba, Brazil",
        "Recife, Pernambuco, Brazil",
        "Natal, Rio Grande do Norte, Brazil",
        "Manaus, Amazonas, Brazil",
        "Maceió, Alagoas, Brazil",
        "Aracaju, Sergipe, Brazil",
        "João Pessoa, Paraíba, Brazil",
        "Caruaru, Pernambuco, Brazil",
    ]:
        assert _vaga(local).combina_com(PERFIL_BR.regras), local
