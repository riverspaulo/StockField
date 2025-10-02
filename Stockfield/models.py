from pydantic import BaseModel 
from typing import List, Optional
from datetime import date
from enum import Enum

class TipoUsuario(str, Enum):
    agricultor = "agricultor"
    admin = "admin"

class StatusProduto(str, Enum):
    disponivel = "disponível"
    esgotado = "esgotado"
    vencido = "vencido"

class Usuario(BaseModel, table=True):
    uuid: Optional[str] = None
    cnpj: str
    nome: str
    email: str
    senha:str
    tipo: TipoUsuario

class Produto(BaseModel, table=True):
    id: Optional[int] = None
    nome: str
    descricao: Optional[str] = None
    categoria: str
    quantidade: int = 0
    preco_unitario: Optional[float] = None
    data_validade: Optional[date] = None
    lote: Optional[str] = None
    fornecedor: Optional[str] = None
    localizacao: Optional[str] = None
    status: StatusProduto

class Estoque(BaseModel, table=True):
    produtos: List[Produto] = []

class Fornecedor(BaseModel, table=True):
    id: Optional[int] = None
    nome: str
    telefone: str
    email: Optional[str] = None

class Movimento(BaseModel, table=True):
    id: Optional[int] = None
    produto_id: int
    tipo: str  # "entrada" ou "saida"
    quantidade: int
    data: date
    fornecedor_id: Optional[int] = None

