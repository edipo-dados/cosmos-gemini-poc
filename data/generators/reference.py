"""Dados de referência fixos: categorias, regiões, segmentos, formas de pagamento."""
from __future__ import annotations

import pandas as pd

# (nome, [substantivos], faixa de preço em reais)
CATEGORIES = [
    ("Eletrônicos", ["Fone de Ouvido", "Carregador", "Caixa de Som", "Smartwatch"], (80, 1800)),
    ("Informática", ["Teclado", "Mouse", "Monitor", "Webcam", "Hub USB"], (40, 2500)),
    ("Celulares e Acessórios", ["Capa", "Película", "Cabo", "Suporte Veicular"], (20, 900)),
    ("Eletrodomésticos", ["Liquidificador", "Cafeteira", "Air Fryer", "Aspirador"], (120, 1500)),
    ("Móveis", ["Estante", "Cadeira", "Mesa", "Poltrona"], (250, 3200)),
    ("Decoração", ["Quadro", "Vaso", "Luminária", "Tapete"], (30, 700)),
    ("Cama, Mesa e Banho", ["Jogo de Cama", "Toalha", "Edredom", "Travesseiro"], (40, 600)),
    ("Esporte e Lazer", ["Bicicleta", "Halter", "Tênis de Corrida", "Bola"], (35, 2200)),
    ("Moda Feminina", ["Vestido", "Blusa", "Saia", "Bolsa"], (50, 650)),
    ("Moda Masculina", ["Camisa", "Calça", "Jaqueta", "Bermuda"], (50, 650)),
    ("Calçados", ["Sapato", "Sandália", "Bota", "Chinelo"], (45, 800)),
    ("Beleza e Perfumaria", ["Perfume", "Hidratante", "Batom", "Shampoo"], (15, 450)),
    ("Saúde e Bem-estar", ["Vitamina", "Massageador", "Termômetro", "Balança"], (20, 500)),
    ("Livros", ["Romance", "Biografia", "Livro Técnico", "HQ"], (15, 180)),
    ("Brinquedos", ["Boneca", "Quebra-cabeça", "Carrinho", "Jogo de Tabuleiro"], (20, 450)),
    ("Games", ["Console", "Controle", "Jogo Digital", "Headset Gamer"], (60, 4200)),
    ("Pet Shop", ["Ração", "Coleira", "Cama Pet", "Brinquedo Pet"], (15, 350)),
    ("Automotivo", ["Capa de Banco", "Aspirador Automotivo", "Pneu", "Som Automotivo"], (30, 1400)),
    ("Ferramentas", ["Furadeira", "Chave de Fenda", "Serra", "Trena"], (25, 900)),
    ("Papelaria", ["Caderno", "Caneta", "Mochila", "Agenda"], (8, 220)),
]
ADJECTIVES = ["Pro", "Plus", "Lite", "Max", "Classic", "Smart", "Eco", "Ultra", "Prime", "Essencial"]

# (nome, estados, peso de clientes)
REGIONS = [
    ("Norte", "AC,AM,AP,PA,RO,RR,TO", 0.06),
    ("Nordeste", "AL,BA,CE,MA,PB,PE,PI,RN,SE", 0.20),
    ("Centro-Oeste", "DF,GO,MS,MT", 0.09),
    ("Sudeste", "ES,MG,RJ,SP", 0.50),
    ("Sul", "PR,RS,SC", 0.15),
]

SEGMENTS = ["Varejo", "Premium", "Corporativo", "Pequena Empresa"]
SEGMENT_WEIGHTS = [0.55, 0.15, 0.10, 0.20]
METHODS = ["credit_card", "pix", "boleto", "debit_card"]
METHOD_WEIGHTS = [0.45, 0.30, 0.15, 0.10]


def categories_df(n: int) -> pd.DataFrame:
    assert n == len(CATEGORIES)
    return pd.DataFrame([(i + 1, c[0]) for i, c in enumerate(CATEGORIES)], columns=["category_id", "name"], dtype=object)


def regions_df() -> pd.DataFrame:
    return pd.DataFrame([(i + 1, r[0], r[1]) for i, r in enumerate(REGIONS)], columns=["region_id", "name", "states"], dtype=object)
