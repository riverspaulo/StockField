from typing import List, Optional, Literal
from datetime import date
from enum import Enum
import sqlite3
from pydantic import BaseModel

DATABASE_URL = "./stockfield.db"

class TipoUsuario(str, Enum):
    agricultor = "agricultor"
    admin = "admin"

class StatusProduto(str, Enum):
    disponivel = "disponível"
    esgotado = "esgotado"
    vencido = "vencido"

class TipoMovimento(str, Enum):
    entrada = "entrada"
    saida = "saída"

class Usuario(BaseModel):
    uuid: Optional[str] = None
    cnpj: str
    nome: str
    email: str
    senha: str
    tipo: TipoUsuario

class Produto(BaseModel):
    uuid: Optional[str] = None
    nome: str
    descricao: Optional[str] = None
    categoria: str
    quantidade: int = 0
    preco_unitario: Optional[float] = None
    data_validade: Optional[date] = None
    lote: Optional[str] = None
    fornecedor_uuid: str
    localizacao: Optional[str] = None
    status: StatusProduto = StatusProduto.disponivel
    usuario_uuid: str

# class Estoque(BaseModel):
#     produtos: List[Produto] = []

class Fornecedor(BaseModel):
    uuid: Optional[str] = None
    nome: str
    telefone: str
    email: Optional[str] = None

class Movimento(BaseModel):
    uuid: Optional[str] = None
    produto_uuid: str
    tipo: Optional[TipoMovimento] = None
    quantidade: int
    data: date
    fornecedor_uuid: str
    usuario_uuid: Optional[str] = None


# Database
def get_db():
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with sqlite3.connect(DATABASE_URL) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            uuid TEXT PRIMARY KEY,
            cnpj TEXT NOT NULL UNIQUE,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL,
            tipo TEXT NOT NULL
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fornecedores (
            uuid TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            telefone TEXT NOT NULL,
            email TEXT NOT NULL
        )""")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            uuid TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            descricao TEXT NOT NULL,
            categoria TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            preco FLOAT NOT NULL,
            data_validade TEXT NOT NULL,
            lote TEXT NOT NULL,
            fornecedor_uuid TEXT NOT NULL,
            localizacao TEXT NOT NULL,
            status TEXT NOT NULL,
            usuario_uuid TEXT NOT NULL,
            FOREIGN KEY (fornecedor_uuid) REFERENCES fornecedores (uuid),
            FOREIGN KEY (usuario_uuid) REFERENCES usuarios (uuid)
        )""")
        
        # Nova tabela para movimentos
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentos (
            uuid TEXT PRIMARY KEY,
            produto_uuid TEXT NOT NULL,
            tipo TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            data TEXT NOT NULL,
            fornecedor_uuid TEXT NOT NULL,
            usuario_uuid TEXT NOT NULL,
            FOREIGN KEY (produto_uuid) REFERENCES produtos (uuid),
            FOREIGN KEY (fornecedor_uuid) REFERENCES fornecedores (uuid),
            FOREIGN KEY (usuario_uuid) REFERENCES usuarios (uuid)
        )""")
        
        conn.commit()