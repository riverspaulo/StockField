from typing import List, Optional, Literal
from datetime import date, datetime, timedelta
from enum import Enum
import sqlite3, uuid
import hashlib
from pydantic import BaseModel
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from PIL import Image as PILImage
from reportlab.lib.utils import ImageReader
from io import BytesIO
from reportlab.lib import colors

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

        cursor.execute("SELECT * FROM usuarios WHERE email = 'admin@admin'")
        admin_existente = cursor.fetchone()

        if not admin_existente:
            adm_uuid = str(uuid.uuid4())
            senha_admin_hash = hashlib.sha256("useradm".encode()).hexdigest()
            cursor.execute(
                """INSERT INTO usuarios VALUES (?, "123.456.789-00", "Admin", "admin@admin", ?, "admin")""",
                (adm_uuid, senha_admin_hash)
            )
        
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

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            uuid TEXT PRIMARY KEY,
            usuario_uuid TEXT NOT NULL,
            acao TEXT NOT NULL,
            detalhes TEXT,
            data TEXT NOT NULL,
            FOREIGN KEY (usuario_uuid) REFERENCES usuarios (uuid)
        )
        """)
        
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


def registrar_log(db, usuario_uuid: str, acao: str, detalhes: str = None):
    cursor = db.cursor()
    log_id = str(uuid.uuid4())
    data = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute("""
        INSERT INTO logs (uuid, usuario_uuid, acao, detalhes, data)
        VALUES (?, ?, ?, ?, ?)
    """, (log_id, usuario_uuid, acao, detalhes, data))

    db.commit()


# Função para recortar a imagem da logo
def cortar_logo(caminho_logo):
    """Remove automaticamente bordas vazias / transparentes da logo."""
    try:
        img = PILImage.open(caminho_logo)
        bbox = img.getbbox()
        if bbox:
            img_crop = img.crop(bbox)
        else:
            img_crop = img
        novo_caminho = caminho_logo.replace(".png", "_crop.png")
        img_crop.save(novo_caminho)

        return novo_caminho
    except Exception as e:
        print("Erro ao recortar logo:", e)
        return caminho_logo



def gerar_pdf_logs(logs, usuario_nome):
    buffer_pdf = BytesIO()

    # Styles
    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        name="TituloRelatorio",
        fontSize=20,
        leading=26,
        textColor=colors.HexColor("#7b9b34"),
        spaceAfter=20,
    )
    style_normal = ParagraphStyle(
        "normal_wrap",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
    )
    style_header = ParagraphStyle(
        "header",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        alignment=1,
        textColor=colors.white
    )

    # Documento
    margin = 2 * cm
    doc = SimpleDocTemplate(
        buffer_pdf,
        pagesize=A4,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=margin
    )

    elementos = []

    # Logo
    logo_path = os.path.join("static", "images", "logo_colorida.png")
    logo_path_crop = cortar_logo(logo_path)

    if os.path.exists(logo_path_crop):
        img_reader = ImageReader(logo_path_crop)
        iw, ih = img_reader.getSize()
        largura = 5 * cm
        proporcao = largura / iw
        altura = ih * proporcao
        img = Image(logo_path_crop, width=largura, height=altura)
        img.hAlign = 'LEFT'
        elementos.append(img)
        elementos.append(Spacer(1, 12))

    # Título
    elementos.append(Paragraph("<br/>Relatório do Estoque", style_title))
    elementos.append(Spacer(1, 12))

    header = [
        Paragraph("Data", style_header),
        Paragraph("Usuário", style_header),
        Paragraph("Ação", style_header),
        Paragraph("Detalhes", style_header)
    ]

    tabela_dados = [header]

    for row in logs:
        data_raw = row["data"] or ""
        usuario = row["usuario_nome"] or ""
        acao = row["acao"] or ""
        detalhes_raw = row["detalhes"] or "-"

        linhas = detalhes_raw.split("|")
        detalhes_formatado = ""
        for linha in linhas:
            if ":" in linha:
                chave, valor = linha.split(":", 1)
                detalhes_formatado += f"<b>{chave.strip()}:</b> {valor.strip()}<br/>"
            else:
                detalhes_formatado += linha.strip() + "<br/>"

        tabela_dados.append([
            Paragraph(data_raw, style_normal),
            Paragraph(usuario, style_normal),
            Paragraph(acao, style_normal),
            Paragraph(detalhes_formatado, style_normal)
        ])


    page_width, page_height = A4
    usable_width = page_width - (2 * margin)

    col_perc = [0.20, 0.25, 0.20, 0.35]
    colWidths = [usable_width * p for p in col_perc]

    total = sum(colWidths)
    if total > usable_width:
        diff = total - usable_width
        colWidths[-1] -= diff

    tabela = Table(tabela_dados, colWidths=colWidths, repeatRows=1)

    # Estilo da tabela
    tabela.setStyle(TableStyle([
        # Cabeçalho
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#96bd3e")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('VALIGN', (0,0), (-1,0), 'MIDDLE'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),

        # Corpo
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor("#1C1C1C")),
        ('VALIGN', (0, 1), (-1, -1), 'TOP'),

        # Padding interno
        ('LEFTPADDING', (0, 1), (-1, -1), 6),
        ('RIGHTPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),

        # Linhas alternadas
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#F8F9F9")]),

        # Bordas suaves
        ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))

    elementos.append(tabela)

    doc.build(elementos)
    buffer_pdf.seek(0)
    return buffer_pdf

