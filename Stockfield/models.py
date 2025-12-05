from typing import List, Optional, Literal
from datetime import date, datetime, timedelta
from enum import Enum
import sqlite3, uuid
import hashlib
from pydantic import BaseModel

DATABASE_URL = "./stockfield.db"

class TipoUsuario(str, Enum):
    agricultor = "agricultor"
    admin = "admin"

class StatusProduto(str, Enum):
    disponivel = "disponível"
    esgotado = "esgotado"
    vencido = "vencido"
    a_vencer = "a_vencer"  
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


class TipoProduto(str, Enum):
    alimento = "alimento"
    defensivo = "defensivo"
    outros = "outros"  

class Produto(BaseModel):
    uuid: Optional[str] = None
    nome: str
    descricao: Optional[str] = None
    categoria: str
    tipo_produto: TipoProduto = TipoProduto.alimento  
    numero_anvisa: Optional[str] = None  
    cuidados_armazenamento: Optional[str] = None  
    tipo_toxico: Optional[str] = None  
    quantidade: int = 0
    estoque_minimo: int = 0
    preco_unitario: Optional[float] = None
    data_validade: Optional[date] = None
    lote: Optional[str] = None
    fornecedor_uuid: str
    localizacao: Optional[str] = None
    status: StatusProduto = StatusProduto.disponivel
    usuario_uuid: Optional[str] = None
    dias_para_vencer: Optional[int] = None

class Fornecedor(BaseModel):
    uuid: Optional[str] = None
    nome: str
    telefone: str
    email: Optional[str] = None
    usuario_uuid: Optional[str] = None

class Movimento(BaseModel):
    uuid: Optional[str] = None
    produto_uuid: str
    tipo: Optional[TipoMovimento] = None
    quantidade: int
    data: date
    fornecedor_uuid: str
    usuario_uuid: Optional[str] = None


def get_db():
    conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
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

        if not cursor.fetchone():
            adm_uuid = str(uuid.uuid4())
            senha_admin_hash = hashlib.sha256("useradm".encode()).hexdigest()
            cursor.execute("""INSERT INTO usuarios VALUES (?, "123.456.789-00", "Admin", "admin@admin", ?, "admin")""",(adm_uuid, senha_admin_hash))
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fornecedores (
            uuid TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            telefone TEXT NOT NULL,
            email TEXT NOT NULL,
            usuario_uuid TEXT NOT NULL,
            FOREIGN KEY (usuario_uuid) REFERENCES usuarios (uuid)
        )""")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            uuid TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            descricao TEXT NOT NULL,
            categoria TEXT NOT NULL,
            tipo_produto TEXT NOT NULL DEFAULT 'alimento',
            numero_anvisa TEXT, 
            cuidados_armazenamento TEXT,
            tipo_toxico TEXT, 
            quantidade INTEGER NOT NULL,
            estoque_minimo INTEGER NOT NULL DEFAULT 0,
            preco_unitario FLOAT,
            data_validade TEXT,
            lote TEXT,
            fornecedor_uuid TEXT NOT NULL,
            localizacao TEXT,
            status TEXT NOT NULL,
            usuario_uuid TEXT NOT NULL,
            dias_para_vencer TEXT,
                       
            FOREIGN KEY (fornecedor_uuid) REFERENCES fornecedores (uuid),
            FOREIGN KEY (usuario_uuid) REFERENCES usuarios (uuid)
        )""")
        
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


def verificar_produtos_a_vencer(db: sqlite3.Connection, dias_alerta: int = 7):
    """
    Verifica produtos que estão próximos do vencimento (hoje + X dias)
    Retorna lista de produtos com status atualizado
    """
    cursor = db.cursor()
    hoje = date.today()
    data_limite = hoje + timedelta(days=dias_alerta)
    
    cursor.execute("""
        SELECT * FROM produtos 
        WHERE data_validade IS NOT NULL 
        AND data_validade != ''
    """)
    
    produtos = cursor.fetchall()
    produtos_atualizados = []
    alertas = []
    
    for produto in produtos:
        produto_dict = dict(produto)
        data_validade_str = produto_dict["data_validade"]
        
        if data_validade_str:
            try:
                data_validade = date.fromisoformat(data_validade_str)
                dias_restantes = (data_validade - hoje).days
                
                novo_status = produto_dict["status"]
                if dias_restantes < 0:
                    # Produto vencido
                    novo_status = StatusProduto.vencido.value
                    alertas.append({
                        "produto": produto_dict["nome"],
                        "uuid": produto_dict["uuid"],
                        "data_validade": data_validade,
                        "status": "vencido",
                        "dias_restantes": dias_restantes,
                        "severidade": "alta"
                    })
                elif dias_restantes <= dias_alerta:
                    # Produto a vencer
                    novo_status = StatusProduto.a_vencer.value
                    alertas.append({
                        "produto": produto_dict["nome"],
                        "uuid": produto_dict["uuid"],
                        "data_validade": data_validade,
                        "status": "a_vencer",
                        "dias_restantes": dias_restantes,
                        "severidade": "media" if dias_restantes > 3 else "alta"
                    })
                else:
                    # Produto ainda tem tempo
                    if produto_dict["status"] in [StatusProduto.a_vencer.value, StatusProduto.vencido.value]:
                        novo_status = StatusProduto.disponivel.value
                
                if novo_status != produto_dict["status"]:
                    cursor.execute(
                        "UPDATE produtos SET status = ? WHERE uuid = ?",
                        (novo_status, produto_dict["uuid"])
                    )
                    produtos_atualizados.append({
                        "uuid": produto_dict["uuid"],
                        "nome": produto_dict["nome"],
                        "status_anterior": produto_dict["status"],
                        "status_novo": novo_status,
                        "dias_restantes": dias_restantes
                    })
                    
            except ValueError:
                continue
    
    if produtos_atualizados:
        db.commit()
    
    return {
        "alertas": alertas,
        "atualizados": produtos_atualizados,
        "total_alertas": len(alertas),
        "data_verificacao": hoje.isoformat()
    }

def obter_alertas_vencimento(db: sqlite3.Connection, usuario_uuid: str = None, dias_alerta: int = 7):
    """
    Obtém alertas de vencimento para um usuário específico
    """
    cursor = db.cursor()
    hoje = date.today()
    
    query = """
        SELECT uuid, nome, data_validade, status, quantidade, lote 
        FROM produtos 
        WHERE data_validade IS NOT NULL 
        AND data_validade != ''
        AND (status = ? OR status = ?)
    """
    params = [StatusProduto.a_vencer.value, StatusProduto.vencido.value]
    
    if usuario_uuid:
        query += " AND usuario_uuid = ?"
        params.append(usuario_uuid)
    
    query += " ORDER BY data_validade ASC"
    
    cursor.execute(query, params)
    produtos = cursor.fetchall()
    
    alertas = []
    for produto in produtos:
        produto_dict = dict(produto)
        data_validade = date.fromisoformat(produto_dict["data_validade"])
        dias_restantes = (data_validade - hoje).days
        
        alertas.append({
            **produto_dict,
            "dias_restantes": dias_restantes,
            "severidade": "vencido" if dias_restantes < 0 else "a_vencer"
        })
    
    return alertas

def obter_resumo_alertas(db: sqlite3.Connection, usuario_uuid: str):
    """
    Retorna resumo de alertas para o painel do usuário
    """
    cursor = db.cursor()
    hoje = date.today()

    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM produtos 
        WHERE usuario_uuid = ? 
        AND status = ?
    """, (usuario_uuid, StatusProduto.vencido.value))
    vencidos = cursor.fetchone()["count"]
    
    # Produtos a vencer (próximos 7 dias)
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM produtos 
        WHERE usuario_uuid = ? 
        AND status = ?
    """, (usuario_uuid, StatusProduto.a_vencer.value))
    a_vencer = cursor.fetchone()["count"]
    

    cursor.execute("""
        SELECT nome, data_validade 
        FROM produtos 
        WHERE usuario_uuid = ? 
        AND data_validade IS NOT NULL 
        AND data_validade != ''
        AND status != ?
        ORDER BY data_validade ASC 
        LIMIT 1
    """, (usuario_uuid, StatusProduto.vencido.value))
    proximo = cursor.fetchone()
    
    proximo_info = None
    if proximo:
        data_validade = date.fromisoformat(proximo["data_validade"])
        dias = (data_validade - hoje).days
        proximo_info = {
            "nome": proximo["nome"],
            "data_validade": data_validade.isoformat(),
            "dias_restantes": dias
        }
    
    return {
        "vencidos": vencidos,
        "a_vencer": a_vencer,
        "proximo_vencimento": proximo_info,
        "total_alertas": vencidos + a_vencer
    }

#FUNÇÕES NOVASSSSSSSSSSS
def verificar_estoque_baixo(db: sqlite3.Connection, usuario_uuid: str = None):
    """
    Verifica produtos com estoque abaixo do mínimo definido
    """
    cursor = db.cursor()
    
    query = """
        SELECT p.*, f.nome as fornecedor_nome 
        FROM produtos p
        LEFT JOIN fornecedores f ON p.fornecedor_uuid = f.uuid
        WHERE p.estoque_minimo > 0 
        AND p.quantidade <= p.estoque_minimo
        AND p.status != 'vencido'
    """
    params = []
    
    if usuario_uuid:
        query += " AND p.usuario_uuid = ?"
        params.append(usuario_uuid)
    
    query += " ORDER BY p.quantidade ASC"
    
    cursor.execute(query, params)
    produtos = cursor.fetchall()
    
    alertas = []
    for produto in produtos:
        produto_dict = dict(produto)
        alertas.append({
            **produto_dict,
            "estoque_atual": produto_dict["quantidade"],
            "estoque_minimo": produto_dict["estoque_minimo"],
            "diferenca": produto_dict["estoque_minimo"] - produto_dict["quantidade"],
            "severidade": "critico" if produto_dict["quantidade"] == 0 else "baixo"
        })
    
    return alertas

def obter_resumo_estoque(db: sqlite3.Connection, usuario_uuid: str):
    """
    Retorna resumo de estoque para o painel do usuário
    """
    cursor = db.cursor()
    
    # Produtos com estoque crítico (abaixo do mínimo)
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM produtos 
        WHERE usuario_uuid = ? 
        AND estoque_minimo > 0 
        AND quantidade <= estoque_minimo
        AND status != 'vencido'
    """, (usuario_uuid,))
    estoque_baixo = cursor.fetchone()["count"]
    
    # Produtos esgotados (quantidade = 0)
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM produtos 
        WHERE usuario_uuid = ? 
        AND quantidade = 0
        AND status != 'vencido'
    """, (usuario_uuid,))
    estoque_esgotado = cursor.fetchone()["count"]
    
    # Produto com estoque mais baixo
    cursor.execute("""
        SELECT nome, quantidade, estoque_minimo 
        FROM produtos 
        WHERE usuario_uuid = ? 
        AND estoque_minimo > 0 
        AND quantidade <= estoque_minimo
        AND status != 'vencido'
        ORDER BY quantidade ASC 
        LIMIT 1
    """, (usuario_uuid,))
    mais_critico = cursor.fetchone()
    
    mais_critico_info = None
    if mais_critico:
        mais_critico_info = {
            "nome": mais_critico["nome"],
            "quantidade": mais_critico["quantidade"],
            "estoque_minimo": mais_critico["estoque_minimo"],
            "necessario": mais_critico["estoque_minimo"] - mais_critico["quantidade"]
        }
    
    # Total de produtos monitorados (com estoque mínimo definido)
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM produtos 
        WHERE usuario_uuid = ? 
        AND estoque_minimo > 0
    """, (usuario_uuid,))
    total_monitorados = cursor.fetchone()["count"]
    
    return {
        "estoque_baixo": estoque_baixo,
        "estoque_esgotado": estoque_esgotado,
        "total_monitorados": total_monitorados,
        "produto_mais_critico": mais_critico_info,
        "total_alertas": estoque_baixo
    }
