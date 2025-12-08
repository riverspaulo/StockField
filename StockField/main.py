#pip install fastapi uvicorn pydantic
#uvicorn main:app

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from typing import List
from datetime import date
import uuid
import sqlite3
import hashlib
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from models import Produto, Usuario, Fornecedor, Movimento, init_db, get_db, TipoUsuario, TipoMovimento, StatusProduto, registrar_log, cortar_logo, gerar_pdf_logs

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="chave_super_secreta")
init_db()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

ALERTA_DIAS = 7

def flash(request: Request, message: str, category: str = "info"):
    if "messages" not in request.session:
        request.session["messages"] = []
    request.session["messages"].append({"message": message, "category": category})

def get_flashed_messages(request: Request):
    messages = request.session.pop("messages") if "messages" in request.session else []
    return messages


@app.middleware("http")
async def verificar_alertas_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/login" and request.method == "POST":
        pass
    
    return response

#ROTAS
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "messages": get_flashed_messages(request)})

@app.get("/login", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "messages": get_flashed_messages(request)})


#MEXI NESSA ROTA MATEUSSSSSS
@app.post("/login")
def login_action(
    request: Request,
    cnpj: str = Form(...),
    senha: str = Form(...),
    db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    senha_hash = hashlib.sha256(senha.encode()).hexdigest()
    
    cursor.execute("SELECT * FROM usuarios WHERE cnpj = ? AND senha = ?", (cnpj, senha_hash))
    user = cursor.fetchone()

    if not user:
        flash(request, "CNPJ ou senha inválidos.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)

    request.session["user"] = {
        "uuid": user["uuid"],
        "nome": user["nome"],
        "email": user["email"],
        "tipo": user["tipo"]
    }

    from models import obter_resumo_estoque
    resumo_estoque = obter_resumo_estoque(db, user["uuid"])
    
    if resumo_estoque["total_alertas"] > 0:
        request.session["alertas_estoque"] = {
            "estoque_baixo": resumo_estoque["estoque_baixo"],
            "estoque_esgotado": resumo_estoque["estoque_esgotado"],
            "total": resumo_estoque["total_alertas"],
            "ultima_verificacao": date.today().isoformat()
        }
        
        mensagem_estoque = f"📦 Atenção! Você tem {resumo_estoque['total_alertas']} produto(s) com estoque baixo "
        if resumo_estoque["estoque_esgotado"] > 0:
            mensagem_estoque += f"({resumo_estoque['estoque_esgotado']} esgotado(s))"
        
        flash(request, mensagem_estoque, "warning")
    

    from models import verificar_produtos_a_vencer, obter_resumo_alertas
    
    resultado = verificar_produtos_a_vencer(db, ALERTA_DIAS)
    resumo = obter_resumo_alertas(db, user["uuid"])
    
    if resumo["total_alertas"] > 0:
        request.session["alertas_vencimento"] = {
            "vencidos": resumo["vencidos"],
            "a_vencer": resumo["a_vencer"],
            "total": resumo["total_alertas"],
            "ultima_verificacao": date.today().isoformat()
        }
        
        mensagem_alerta = f"⚠️ Atenção! Você tem {resumo['total_alertas']} produto(s) "
        if resumo["vencidos"] > 0 and resumo["a_vencer"] > 0:
            mensagem_alerta += f"({resumo['vencidos']} vencido(s) e {resumo['a_vencer']} próximo(s) do vencimento)"
        elif resumo["vencidos"] > 0:
            mensagem_alerta += f"({resumo['vencidos']} vencido(s))"
        else:
            mensagem_alerta += f"({resumo['a_vencer']} próximo(s) do vencimento)"
        
        flash(request, mensagem_alerta, "warning")
    
    flash(request, f"Bem-vindo(a), {user['nome']}!", "success")
    
  
    if user["tipo"] == "admin":
        url = request.url_for("profile_admin")
    else:
        url = request.url_for("profile")
    
    return RedirectResponse(url=url, status_code=303)

@app.get("/cadastro", response_class=HTMLResponse)
def cadastro(request: Request):
    return templates.TemplateResponse("cadastro.html", {"request": request, "messages": get_flashed_messages(request)})

@app.post("/cadastro")
def cadastro_action(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    cnpj: str = Form(...),
    tipo_usuario: str = Form(...),
    senha: str = Form(...),
    confirmar_senha: str = Form(...),
    db: sqlite3.Connection = Depends(get_db)
):
    if senha != confirmar_senha:
        flash(request, "As senhas não coincidem!", "error")
        url = request.url_for("cadastro")
        return RedirectResponse(url=url, status_code=303)

    cursor = db.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
    if cursor.fetchone():
        flash(request, "E-mail já cadastrado!", "error")
        url = request.url_for("cadastro")
        return RedirectResponse(url=url, status_code=303)
    
    cursor.execute("SELECT * FROM usuarios WHERE cnpj = ?", (cnpj,))
    if cursor.fetchone():
        flash(request, "CNPJ já cadastrado!", "error")
        url = request.url_for("cadastro")
        return RedirectResponse(url=url, status_code=303)

    tipos_validos = [tipo.value for tipo in TipoUsuario]
    if tipo_usuario not in tipos_validos:
        flash(request, "Tipo de usuário inválido!", "error")
        url = request.url_for("cadastro")
        return RedirectResponse(url=url, status_code=303)

    senha_hash = hashlib.sha256(senha.encode()).hexdigest()
    
    novo_uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?, ?)",
        (novo_uuid, cnpj, nome, email, senha_hash, tipo_usuario)  # Usa senha_hash
    )
    db.commit()
    flash(request, "Cadastro realizado com sucesso! Faça login para continuar.", "success")

    url = request.url_for("login")
    return RedirectResponse(url=url, status_code=303)


#MATEUSSSSSSS
@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)

    user = request.session.get("user", {})
    if user.get("tipo") == "admin":
        url = request.url_for("profile_admin")
        
        return RedirectResponse(url=url, status_code=303)
    return templates.TemplateResponse("profile.html", {
        "request": request, 
        "messages": get_flashed_messages(request),
        "user": user
    })

#ISSO É NOVO MATEUS 
@app.get("/profile_admin", response_class=HTMLResponse)
def profile_admin(request: Request):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    
    user = request.session.get("user", {})
    if user.get("tipo") != "admin":
        flash(request, "Acesso restrito a administradores.", "error")
        url = request.url_for("profile")
        return RedirectResponse(url=url, status_code=303)
    
    return templates.TemplateResponse("profile_admin.html", {
        "request": request, 
        "messages": get_flashed_messages(request),
        "user": user
    })


@app.get("/api/alertas/vencimento")
def obter_alertas_vencimento_api(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """API para obter alertas de vencimento"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    from models import obter_alertas_vencimento, verificar_produtos_a_vencer
    
    verificar_produtos_a_vencer(db, ALERTA_DIAS)
    
    usuario_uuid = request.session["user"]["uuid"]
    alertas = obter_alertas_vencimento(db, usuario_uuid, ALERTA_DIAS)
    
    return {
        "alertas": alertas,
        "total": len(alertas),
        "dias_alerta": ALERTA_DIAS,
        "data_consulta": date.today().isoformat()
    }

@app.get("/api/alertas/resumo")
def obter_resumo_alertas_api(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """API para obter resumo de alertas"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    from models import obter_resumo_alertas
    
    usuario_uuid = request.session["user"]["uuid"]
    resumo = obter_resumo_alertas(db, usuario_uuid)
    
    return resumo

@app.post("/api/produtos/{uuid}/verificar-validade")
def verificar_validade_produto(
    uuid: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Verifica validade de um produto específico"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (uuid,))
    produto = cursor.fetchone()
    
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    produto_dict = dict(produto)
    
    if not produto_dict["data_validade"]:
        return {
            "status": "sem_validade",
            "mensagem": "Produto não possui data de validade"
        }
    
    data_validade = date.fromisoformat(produto_dict["data_validade"])
    hoje = date.today()
    dias_restantes = (data_validade - hoje).days
    
    status = "ok"
    if dias_restantes < 0:
        status = "vencido"
    elif dias_restantes <= ALERTA_DIAS:
        status = "a_vencer"
    
    return {
        "produto": produto_dict["nome"],
        "data_validade": data_validade.isoformat(),
        "dias_restantes": dias_restantes,
        "status": status,
        "status_atual": produto_dict["status"],
        "recomendacao": "Consumir imediatamente" if dias_restantes <= 3 else "Atenção ao prazo"
    }

# ROTAS DE MOVIMENTAÇÕES
@app.get("/movimentacoes", response_class=HTMLResponse)
def pagina_movimentacoes(request: Request):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    
    return templates.TemplateResponse("movimentacoes.html", {
        "request": request, 
        "messages": get_flashed_messages(request),
        "user": request.session["user"]
    })

@app.get("/movimentos/", response_model=List[Movimento])
def listar_movimentos(request: Request, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    usuario_uuid = request.session["user"]["uuid"]  
    cursor.execute("""
        SELECT m.*, p.nome as produto_nome, f.nome as fornecedor_nome 
        FROM movimentos m
        LEFT JOIN produtos p ON m.produto_uuid = p.uuid
        LEFT JOIN fornecedores f ON m.fornecedor_uuid = f.uuid
        WHERE m.usuario_uuid = ?  
        ORDER BY m.data DESC
    """, (usuario_uuid,))
    movimentos_data = cursor.fetchall()
    
    movimentos = []
    for row in movimentos_data:
        movimento_dict = dict(row)
        movimento_dict["data"] = date.fromisoformat(movimento_dict["data"])
        movimento = Movimento(**{k: v for k, v in movimento_dict.items() if k in Movimento.__fields__})
        movimentos.append(movimento)
    
    return movimentos

@app.get("/produtos/{uuid}", response_model=Produto)
def obter_produto_por_uuid(request:Request, uuid: str, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (uuid,))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    produto_dict = dict(produto)
    if produto_dict["data_validade"]:
        produto_dict["data_validade"] = date.fromisoformat(produto_dict["data_validade"])
    return Produto(**produto_dict)


#MAIS UMA MATEUSSSSSSSSSS
@app.post("/movimentos/entrada", response_model=Movimento)
def registrar_entrada(movimento: Movimento, request: Request, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    usuario_uuid = str(request.session["user"]["uuid"])
    movimento.usuario_uuid = usuario_uuid

    cursor.execute("SELECT * FROM produtos WHERE uuid = ? AND usuario_uuid = ?", (movimento.produto_uuid, movimento.usuario_uuid))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado ou não pertence ao usuário.")
    
    cursor.execute("SELECT * FROM fornecedores WHERE uuid = ?", (movimento.fornecedor_uuid,))
    fornecedor = cursor.fetchone()
    if not fornecedor:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
    
    movimento.uuid = str(uuid.uuid4())
    movimento.tipo = TipoMovimento.entrada

    cursor.execute(
        "INSERT INTO movimentos VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            movimento.uuid,
            movimento.produto_uuid,
            movimento.tipo.value,
            movimento.quantidade,
            movimento.data.isoformat(),
            movimento.fornecedor_uuid,
            movimento.usuario_uuid  
        )
    )

    nova_quantidade = produto["quantidade"] + movimento.quantidade
    novo_status = "disponível" if nova_quantidade > 0 else "esgotado"

    cursor.execute(
        "UPDATE produtos SET quantidade = ?, status = ? WHERE uuid = ?",
        (nova_quantidade, novo_status, movimento.produto_uuid)
    )

    from models import verificar_estoque_baixo
    alertas_estoque = verificar_estoque_baixo(db, usuario_uuid)
    
    if alertas_estoque:
        request.session["alertas_estoque"] = {
            "total": len(alertas_estoque),
            "data_verificacao": date.today().isoformat()
        }
    
    db.commit()

    # Registrar log da entrada
    detalhes = (
    f"Movimento UUID: {movimento.uuid} | "
    f"Produto: {produto['nome']} | "
    f"Quantidade: +{movimento.quantidade} unidades | "
    f"Fornecedor: {fornecedor['nome']} | "
    f"Data: {movimento.data.isoformat()}"
)
    registrar_log(db, usuario_uuid, "Entrada de Estoque", detalhes)

    return movimento

#MATEUSSSSSSSSSSSSSSSSSSSS
@app.post("/movimentos/saida", response_model=Movimento)
def registrar_saida(movimento: Movimento, request: Request, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    usuario_uuid = str(request.session["user"]["uuid"])
    cursor.execute("SELECT * FROM produtos WHERE uuid = ? AND usuario_uuid = ?", (movimento.produto_uuid, usuario_uuid))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado ou não pertence ao usuário.")
    
    if produto["quantidade"] < movimento.quantidade:
        raise HTTPException(status_code=400, detail="Estoque insuficiente")
    
    cursor.execute("SELECT * FROM fornecedores WHERE uuid = ?", (movimento.fornecedor_uuid,))
    fornecedor = cursor.fetchone()
    if not fornecedor:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
   
    movimento.uuid = str(uuid.uuid4())
    movimento.tipo = TipoMovimento.saida
    movimento.usuario_uuid = usuario_uuid
    
    cursor.execute(
        "INSERT INTO movimentos VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            movimento.uuid,
            movimento.produto_uuid,
            movimento.tipo.value,
            movimento.quantidade,
            movimento.data.isoformat(),
            movimento.fornecedor_uuid,
            movimento.usuario_uuid 
        )
    )
    
    nova_quantidade = produto["quantidade"] - movimento.quantidade
    novo_status = "disponível" if nova_quantidade > 0 else "esgotado"
    
    cursor.execute(
        "UPDATE produtos SET quantidade = ?, status = ? WHERE uuid = ?",
        (nova_quantidade, novo_status, movimento.produto_uuid)
    )

    from models import verificar_estoque_baixo
    alertas_estoque = verificar_estoque_baixo(db, usuario_uuid)
    
    if alertas_estoque:
        request.session["alertas_estoque"] = {
            "total": len(alertas_estoque),
            "data_verificacao": date.today().isoformat()
        }
    
    db.commit()

    detalhes = (
        f"Movimento UUID: {movimento.uuid} | "
        f"Produto: {produto['nome']} | "
        f"Quantidade: -{movimento.quantidade} unidades | "
        f"Data: {movimento.data.isoformat()}"
    )
    registrar_log(db, usuario_uuid, "Saída de Estoque", detalhes)

    return movimento


# ROTAS DA API - CORREÇÃO DAS ROTAS CRÍTICAS
@app.post("/usuarios/", response_model=Usuario)
def cadastrar_usuario(usuario: Usuario, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    usuario.uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?, ?)",
        (usuario.uuid, usuario.cnpj, usuario.nome, usuario.email, usuario.senha, usuario.tipo.value)
    )
    db.commit()
    return usuario


@app.post("/produtos/", response_model=Produto)
def cadastrar_produto(request: Request, produto: Produto, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    produto.uuid = str(uuid.uuid4())
    usuario_uuid = request.session["user"]["uuid"]
    produto.usuario_uuid = usuario_uuid
    
    dias_para_vencer = None
    if produto.data_validade:
        hoje = date.today()
        dias_restantes = (produto.data_validade - hoje).days
        
        if dias_restantes < 0:
            produto.status = StatusProduto.vencido
            dias_para_vencer = dias_restantes
        elif dias_restantes <= ALERTA_DIAS:
            produto.status = StatusProduto.a_vencer
            dias_para_vencer = dias_restantes
        else:
            dias_para_vencer = dias_restantes

    cursor.execute("SELECT * FROM fornecedores WHERE uuid = ?", (produto.fornecedor_uuid,))
    fornecedor = cursor.fetchone()
    
    cursor.execute(
        "INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",  
        (
            produto.uuid,                    
            produto.nome,                    
            produto.descricao,               
            produto.categoria,               
            produto.numero_anvisa,           
            produto.cuidados_armazenamento,  
            produto.tipo_toxico,             
            produto.quantidade,              
            produto.estoque_minimo,          
            produto.preco_unitario,          
            produto.data_validade.isoformat() if produto.data_validade else None, 
            produto.lote,                    
            produto.fornecedor_uuid,         
            produto.localizacao,             
            produto.status.value,            
            usuario_uuid,                    
            dias_para_vencer,                 
        )
    )
    db.commit()
    
    detalhes = (
        f"UUID: {produto.uuid} | "
        f"Produto: {produto.nome}| "
        f"Quantidade: {produto.quantidade} unidades | "
        f"Fornecedor: {fornecedor['nome']} | "
        f"Data de validade: {produto.data_validade.isoformat()}"
    )
    registrar_log(db, usuario_uuid, "Novo Produto Cadastrado", detalhes)
    return produto


@app.get("/produtos_admin", response_class=HTMLResponse)
def pagina_produtos_admin(request: Request):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    
    user = request.session.get("user", {})
    if user.get("tipo") != "admin":
        flash(request, "Acesso restrito a administradores.", "error")
        url = request.url_for("profile")
        return RedirectResponse(url=url, status_code=303)
    
    return templates.TemplateResponse("produtos_admin.html", {
        "request": request, 
        "messages": get_flashed_messages(request),
        "user": user
    })

@app.post("/fornecedores/", response_model=Fornecedor)
def cadastrar_fornecedor(request:Request, fornecedor: Fornecedor, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    usuario_uuid = request.session["user"]["uuid"]
    fornecedor.uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO fornecedores VALUES (?, ?, ?, ?, ?)",
        (fornecedor.uuid, fornecedor.nome, fornecedor.telefone, fornecedor.email, usuario_uuid)
    )
    db.commit()

    detalhes = (
        f"UUID: {fornecedor.uuid} | "
        f"Nome: {fornecedor.nome} | "
    )
    registrar_log(db, usuario_uuid, "Novo Fornecedor Cadastrado", detalhes)
    return fornecedor

@app.get("/fornecedores_admin", response_class=HTMLResponse)
def pagina_fornecedores_admin(request: Request):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    
    user = request.session.get("user", {})
    if user.get("tipo") != "admin":
        flash(request, "Acesso restrito a administradores.", "error")
        url = request.url_for("profile")
        return RedirectResponse(url=url, status_code=303)
    
    return templates.TemplateResponse("fornecedores_admin.html", {
        "request": request, 
        "messages": get_flashed_messages(request),
        "user": user
    })

@app.get("/produtos/", response_model=List[Produto])
def listar_produtos(request: Request, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    usuario_uuid = request.session["user"]["uuid"] 
    cursor.execute("SELECT * FROM produtos WHERE usuario_uuid = ?", (usuario_uuid,))
    produtos = []
    for row in cursor.fetchall():
        produto_dict = dict(row)
        if produto_dict["data_validade"]:
            produto_dict["data_validade"] = date.fromisoformat(produto_dict["data_validade"])
        produtos.append(Produto(**produto_dict))
    return produtos

@app.get("/produtos/{nome}", response_model=Produto)
def obter_produto(request:Request, nome: str, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE nome = ?", (nome,))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    produto_dict = dict(produto)
    if produto_dict["data_validade"]:
        produto_dict["data_validade"] = date.fromisoformat(produto_dict["data_validade"])
    return Produto(**produto_dict)

@app.delete("/produtos/{uuid}", response_model=dict)
def deletar_produto(request:Request, uuid: str, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (uuid,))
    produto = cursor.fetchone()
    usuario_uuid = request.session["user"]["uuid"]
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    cursor.execute("DELETE FROM produtos WHERE uuid = ?", (uuid,))
    db.commit()
    # Registrar log
    detalhes = (
        f"UUID: {produto["uuid"]} | "
        f"Nome: {produto["nome"]} | "
    )
    registrar_log(db, usuario_uuid, "Produto Deletado", detalhes)
    return {"message": "Produto deletado com sucesso"}

# @app.get("/fornecedores/", response_model=List[Fornecedor])
# def listar_fornecedores(request:Request, db: sqlite3.Connection = Depends(get_db)):
#     cursor = db.cursor()
#     usuario_uuid = request.session["user"]["uuid"] 
#     cursor.execute("SELECT * FROM fornecedores WHERE usuario_uuid = ?", (usuario_uuid,))
#     fornecedores = [Fornecedor(**dict(row)) for row in cursor.fetchall()]
#     return fornecedores

@app.get("/fornecedores/", response_model=List[Fornecedor])
def listar_fornecedores(request: Request, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    usuario_uuid = request.session["user"]["uuid"] 
    
    # Query aprimorada para incluir estatísticas detalhadas
    cursor.execute("""
        SELECT 
            f.*,
            COUNT(DISTINCT p.uuid) as produtos_count,
            COUNT(DISTINCT m.uuid) as entradas_count,
            COUNT(DISTINCT CASE WHEN m.tipo = 'entrada' THEN m.uuid END) as total_entradas,
            COUNT(DISTINCT CASE WHEN m.tipo = 'saida' THEN m.uuid END) as total_saidas,
            COALESCE(SUM(CASE WHEN m.tipo = 'entrada' THEN m.quantidade ELSE 0 END), 0) as quantidade_total_entradas,
            COALESCE(SUM(CASE WHEN m.tipo = 'saida' THEN m.quantidade ELSE 0 END), 0) as quantidade_total_saidas
        FROM fornecedores f
        LEFT JOIN produtos p ON f.uuid = p.fornecedor_uuid AND p.usuario_uuid = f.usuario_uuid
        LEFT JOIN movimentos m ON f.uuid = m.fornecedor_uuid AND m.usuario_uuid = f.usuario_uuid
        WHERE f.usuario_uuid = ?
        GROUP BY f.uuid
        ORDER BY f.nome
    """, (usuario_uuid,))
    
    fornecedores_com_stats = []
    for row in cursor.fetchall():
        fornecedor_dict = dict(row)
        
        # Obter lista de produtos deste fornecedor
        cursor.execute("""
            SELECT uuid, nome, quantidade, status, data_validade, lote
            FROM produtos 
            WHERE fornecedor_uuid = ? AND usuario_uuid = ?
            ORDER BY nome
        """, (fornecedor_dict["uuid"], usuario_uuid))
        produtos = cursor.fetchall()
        
        # Obter lista de movimentos deste fornecedor
        cursor.execute("""
            SELECT m.uuid, m.tipo, m.quantidade, m.data, p.nome as produto_nome
            FROM movimentos m
            LEFT JOIN produtos p ON m.produto_uuid = p.uuid
            WHERE m.fornecedor_uuid = ? AND m.usuario_uuid = ?
            ORDER BY m.data DESC
            LIMIT 10
        """, (fornecedor_dict["uuid"], usuario_uuid))
        movimentos = cursor.fetchall()
        
        # Adicionar dados detalhados
        fornecedor_dict["produtos_detalhados"] = [dict(produto) for produto in produtos]
        fornecedor_dict["movimentos_detalhados"] = [dict(movimento) for movimento in movimentos]
        fornecedor_dict["quantidade_produtos"] = len(produtos)
        
        fornecedores_com_stats.append(fornecedor_dict)
    
    return fornecedores_com_stats


@app.get("/fornecedores", response_class=HTMLResponse)
def pagina_fornecedores(request: Request):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    
    return templates.TemplateResponse("fornecedores.html", {
        "request": request, 
        "messages": get_flashed_messages(request),
        "user": request.session["user"]
    })

@app.get("/fornecedores/{uuid}", response_model=Fornecedor)
def obter_fornecedor_por_uuid(
    request: Request,
    uuid: str, 
    db: sqlite3.Connection = Depends(get_db)
):
    """Obtém um fornecedor específico por UUID"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    cursor = db.cursor()
    cursor.execute("SELECT * FROM fornecedores WHERE uuid = ?", (uuid,))
    fornecedor = cursor.fetchone()
    
    if not fornecedor:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
    
    return Fornecedor(**dict(fornecedor))

@app.put("/fornecedores/{uuid}", response_model=Fornecedor)
def atualizar_fornecedor(request:Request, uuid: str, fornecedor: Fornecedor, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    cursor.execute("SELECT * FROM fornecedores WHERE uuid = ?", (uuid,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
    
    cursor.execute(
        "UPDATE fornecedores SET nome = ?, telefone = ?, email = ? WHERE uuid = ?",
        (fornecedor.nome, fornecedor.telefone, fornecedor.email, uuid)
    )
    db.commit()
    
    fornecedor.uuid = uuid
    return fornecedor

@app.delete("/fornecedores/{uuid}", response_model=dict)
def deletar_fornecedor(request:Request, uuid: str, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    cursor.execute("SELECT * FROM fornecedores WHERE uuid = ?", (uuid,))
    fornecedor = cursor.fetchone()
    usuario_uuid = request.session["user"]["uuid"]
    if not fornecedor:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
   
    cursor.execute("SELECT * FROM produtos WHERE fornecedor_uuid = ?", (uuid,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="Não é possível excluir fornecedor com produtos vinculados")
    
    cursor.execute("DELETE FROM fornecedores WHERE uuid = ?", (uuid,))
    db.commit()
    # Registrar log
    detalhes = (
        f"UUID: {fornecedor["uuid"]} | "
        f"Nome: {fornecedor["nome"]} | "
    )
    registrar_log(db, usuario_uuid, "Fornecedor Deletado", detalhes)
    return {"message": "Fornecedor deletado com sucesso"}


@app.get("/produtos", response_class=HTMLResponse)
def pagina_produtos(request: Request):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    
    return templates.TemplateResponse("produtos.html", {
        "request": request, 
        "messages": get_flashed_messages(request),
        "user": request.session["user"]
    })


#MEXI NESSA AQUIII MATEUSSSSSSSSSSSSSSSSSSSSSSSS
#MEXI AQUI TAMBÉM MICKA
@app.put("/produtos/{uuid}", response_model=Produto)
def atualizar_produto(uuid: str, produto: Produto, request: Request, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (uuid,))
    produto_existente = cursor.fetchone()
    if not produto_existente:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    if produto.data_validade:
        hoje = date.today()
        dias_restantes = (produto.data_validade - hoje).days
        
        if dias_restantes < 0:
            produto.status = StatusProduto.vencido
        elif dias_restantes <= ALERTA_DIAS:
            produto.status = StatusProduto.a_vencer
        else:
            produto.status = StatusProduto.disponivel
    
    cursor.execute(
        """UPDATE produtos SET 
            nome = ?, descricao = ?, categoria = ?,
            numero_anvisa = ?, cuidados_armazenamento = ?, tipo_toxico = ?,
            quantidade = ?, estoque_minimo = ?, preco_unitario = ?, data_validade = ?, lote = ?, 
            fornecedor_uuid = ?, localizacao = ?, status = ? 
        WHERE uuid = ?""",
        (
            produto.nome,
            produto.descricao,
            produto.categoria,
            produto.numero_anvisa,
            produto.cuidados_armazenamento,
            produto.tipo_toxico,
            produto.quantidade,
            produto.estoque_minimo,
            produto.preco_unitario,
            produto.data_validade.isoformat() if produto.data_validade else None,
            produto.lote,
            produto.fornecedor_uuid,
            produto.localizacao,
            produto.status.value,
            uuid
        )
    )
    db.commit()
    
    produto.uuid = uuid
    return produto

@app.post("/api/alertas/verificar")
def forcar_verificacao_alertas(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Força verificação de alertas de vencimento"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    from models import verificar_produtos_a_vencer, obter_resumo_alertas
    
    resultado = verificar_produtos_a_vencer(db, ALERTA_DIAS)
    usuario_uuid = request.session["user"]["uuid"]
    resumo = obter_resumo_alertas(db, usuario_uuid)
    
    return {
        "verificacao": resultado,
        "resumo_usuario": resumo,
        "mensagem": f"Verificação concluída. {resumo['total_alertas']} alerta(s) encontrado(s)."
    }

@app.get("/produtos/editar/{uuid}", response_model=Produto)
def obter_produto_edicao(request:Request, uuid: str, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (uuid,))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    produto_dict = dict(produto)
    if produto_dict["data_validade"]:
        produto_dict["data_validade"] = date.fromisoformat(produto_dict["data_validade"])
    return Produto(**produto_dict)


# ROTA PARA ALERTAS DE ESTOQUE BAIXO - NOVAS ROTAS MATEUSSSSSSSSSS
@app.get("/api/alertas/estoque")
def obter_alertas_estoque_api(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """API para obter alertas de estoque baixo"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    from models import verificar_estoque_baixo
    
    usuario_uuid = request.session["user"]["uuid"]
    alertas = verificar_estoque_baixo(db, usuario_uuid)
    
    return {
        "alertas": alertas,
        "total": len(alertas),
        "data_consulta": date.today().isoformat()
    }

# ROTA PARA RESUMO DE ESTOQUE
@app.get("/api/estoque/resumo")
def obter_resumo_estoque_api(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """API para obter resumo de estoque"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    from models import obter_resumo_estoque
    
    usuario_uuid = request.session["user"]["uuid"]
    resumo = obter_resumo_estoque(db, usuario_uuid)
    
    return resumo

# PÁGINA DE ESTOQUE CRÍTICO
@app.get("/estoque-critico", response_class=HTMLResponse)
def pagina_estoque_critico(request: Request):
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    
    return templates.TemplateResponse("estoque_critico.html", {
        "request": request, 
        "messages": get_flashed_messages(request),
        "user": request.session["user"]
    })


#ROTAS DOS ADMINISTRADORES 
@app.get("/api/admin/usuarios")
def listar_todos_usuarios(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Lista todos os usuários do sistema (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    cursor.execute("SELECT uuid, cnpj, nome, email, tipo FROM usuarios ORDER BY nome")
    usuarios = cursor.fetchall()
    
    return [dict(usuario) for usuario in usuarios]

@app.get("/api/admin/usuarios/estatisticas")
def obter_estatisticas_usuarios(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Obtém estatísticas dos usuários (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    
    # Total de usuários
    cursor.execute("SELECT COUNT(*) as total FROM usuarios")
    total_usuarios = cursor.fetchone()["total"]
    
    # Total de agricultores
    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE tipo = 'agricultor'")
    total_agricultores = cursor.fetchone()["total"]
    
    # Total de administradores
    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE tipo = 'admin'")
    total_admins = cursor.fetchone()["total"]
    
    # Total de produtos
    cursor.execute("SELECT COUNT(*) as total FROM produtos")
    total_produtos = cursor.fetchone()["total"]
    
    print(f"DEBUG - Estatísticas: usuarios={total_usuarios}, agricultores={total_agricultores}, admins={total_admins}, produtos={total_produtos}")  # Para debug
    
    return {
        "total_usuarios": total_usuarios,
        "total_agricultores": total_agricultores,
        "total_admins": total_admins,
        "total_produtos": total_produtos
    }


@app.post("/api/admin/usuarios")
def criar_usuario_admin(
    request: Request,
    usuario: Usuario,
    db: sqlite3.Connection = Depends(get_db)
):
    """Cria um novo usuário (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    
    # Verifica se email já existe
    cursor.execute("SELECT * FROM usuarios WHERE email = ?", (usuario.email,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")
    
    # Verifica se CNPJ já existe
    cursor.execute("SELECT * FROM usuarios WHERE cnpj = ?", (usuario.cnpj,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="CNPJ já cadastrado")
    

    usuario.uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?, ?)",
        (
            usuario.uuid,
            usuario.cnpj,
            usuario.nome,
            usuario.email,
            usuario.senha,
            usuario.tipo.value
        )
    )
    
    db.commit()
    
    return {
        "uuid": usuario.uuid,
        "cnpj": usuario.cnpj,
        "nome": usuario.nome,
        "email": usuario.email,
        "tipo": usuario.tipo.value
    }

@app.put("/api/admin/usuarios/{uuid}")
def atualizar_usuario_admin(
    uuid: str,
    request: Request,
    usuario_data: dict,
    db: sqlite3.Connection = Depends(get_db)
):
    """Atualiza um usuário (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE uuid = ?", (uuid,))
    usuario_existente = cursor.fetchone()
    if not usuario_existente:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    if usuario_data.get("email") != usuario_existente["email"]:
        cursor.execute("SELECT * FROM usuarios WHERE email = ? AND uuid != ?", 
                      (usuario_data["email"], uuid))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="E-mail já cadastrado")
 
    if usuario_data.get("cnpj") != usuario_existente["cnpj"]:
        cursor.execute("SELECT * FROM usuarios WHERE cnpj = ? AND uuid != ?", 
                      (usuario_data["cnpj"], uuid))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="CNPJ já cadastrado")
    
    update_fields = []
    update_values = []
    
    if "nome" in usuario_data:
        update_fields.append("nome = ?")
        update_values.append(usuario_data["nome"])
    
    if "email" in usuario_data:
        update_fields.append("email = ?")
        update_values.append(usuario_data["email"])
    
    if "cnpj" in usuario_data:
        update_fields.append("cnpj = ?")
        update_values.append(usuario_data["cnpj"])
    
    if "tipo" in usuario_data:
        update_fields.append("tipo = ?")
        update_values.append(usuario_data["tipo"])
    
    if "senha" in usuario_data and usuario_data["senha"]:
        update_fields.append("senha = ?")
        update_values.append(usuario_data["senha"])
    
    if update_fields:
        update_values.append(uuid)
        query = f"UPDATE usuarios SET {', '.join(update_fields)} WHERE uuid = ?"
        cursor.execute(query, update_values)
        db.commit()
    
    cursor.execute("SELECT uuid, cnpj, nome, email, tipo FROM usuarios WHERE uuid = ?", (uuid,))
    usuario_atualizado = cursor.fetchone()
    
    return dict(usuario_atualizado)

@app.delete("/api/admin/usuarios/{uuid}")
def deletar_usuario_admin(
    uuid: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Deleta um usuário (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
 
    if user.get("uuid") == uuid:
        raise HTTPException(status_code=400, detail="Não é possível excluir sua própria conta")
    
    cursor = db.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE uuid = ?", (uuid,))
    usuario = cursor.fetchone()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    cursor.execute("SELECT COUNT(*) as total FROM produtos WHERE usuario_uuid = ?", (uuid,))
    total_produtos = cursor.fetchone()["total"]
    
    if total_produtos > 0:
        raise HTTPException(
            status_code=400, 
            detail="Não é possível excluir usuário com produtos cadastrados"
        )
    
    cursor.execute("DELETE FROM usuarios WHERE uuid = ?", (uuid,))
    db.commit()
    
    return {"message": "Usuário excluído com sucesso"}



@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    flash(request, "Você saiu do sistema.", "info")
    return response



@app.get("/api/admin/usuarios")
def listar_todos_usuarios(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Lista todos os usuários do sistema (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    cursor.execute("SELECT uuid, cnpj, nome, email, tipo FROM usuarios ORDER BY nome")
    usuarios = cursor.fetchall()
    
    return [dict(usuario) for usuario in usuarios]

@app.get("/api/admin/usuarios/{uuid}")
def obter_usuario_admin(
    uuid: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Obtém um usuário específico (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    cursor.execute("SELECT uuid, cnpj, nome, email, tipo FROM usuarios WHERE uuid = ?", (uuid,))
    usuario = cursor.fetchone()
    
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    return dict(usuario)

@app.get("/api/admin/usuarios/recentes")
def obter_usuarios_recentes(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Obtém os últimos usuários cadastrados (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    cursor.execute("""
        SELECT uuid, cnpj, nome, email, tipo 
        FROM usuarios 
        ORDER BY rowid DESC 
        LIMIT 5
    """)
    usuarios = cursor.fetchall()
    
    return [dict(usuario) for usuario in usuarios]

@app.post("/api/admin/usuarios")
def criar_usuario_admin(
    request: Request,
    usuario: Usuario,
    db: sqlite3.Connection = Depends(get_db)
):
    """Cria um novo usuário (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    
    cursor.execute("SELECT * FROM usuarios WHERE email = ?", (usuario.email,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")
    
    cursor.execute("SELECT * FROM usuarios WHERE cnpj = ?", (usuario.cnpj,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="CNPJ já cadastrado")
    
    usuario.uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?, ?)",
        (
            usuario.uuid,
            usuario.cnpj,
            usuario.nome,
            usuario.email,
            usuario.senha,
            usuario.tipo.value
        )
    )
    
    db.commit()

    return {
        "uuid": usuario.uuid,
        "cnpj": usuario.cnpj,
        "nome": usuario.nome,
        "email": usuario.email,
        "tipo": usuario.tipo.value
    }

@app.put("/api/admin/usuarios/{uuid}")
def atualizar_usuario_admin(
    uuid: str,
    request: Request,
    usuario_data: dict,
    db: sqlite3.Connection = Depends(get_db)
):
    """Atualiza um usuário (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE uuid = ?", (uuid,))
    usuario_existente = cursor.fetchone()
    if not usuario_existente:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    if usuario_data.get("email") != usuario_existente["email"]:
        cursor.execute("SELECT * FROM usuarios WHERE email = ? AND uuid != ?", 
                      (usuario_data["email"], uuid))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="E-mail já cadastrado")

    if usuario_data.get("cnpj") != usuario_existente["cnpj"]:
        cursor.execute("SELECT * FROM usuarios WHERE cnpj = ? AND uuid != ?", 
                      (usuario_data["cnpj"], uuid))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="CNPJ já cadastrado")
    
    update_fields = []
    update_values = []
    
    if "nome" in usuario_data:
        update_fields.append("nome = ?")
        update_values.append(usuario_data["nome"])
    
    if "email" in usuario_data:
        update_fields.append("email = ?")
        update_values.append(usuario_data["email"])
    
    if "cnpj" in usuario_data:
        update_fields.append("cnpj = ?")
        update_values.append(usuario_data["cnpj"])
    
    if "tipo" in usuario_data:
        update_fields.append("tipo = ?")
        update_values.append(usuario_data["tipo"])
    
    if "senha" in usuario_data and usuario_data["senha"]:
        update_fields.append("senha = ?")
        update_values.append(usuario_data["senha"])
    
    if update_fields:
        update_values.append(uuid)
        query = f"UPDATE usuarios SET {', '.join(update_fields)} WHERE uuid = ?"
        cursor.execute(query, update_values)
        db.commit()
    
   
    cursor.execute("SELECT uuid, cnpj, nome, email, tipo FROM usuarios WHERE uuid = ?", (uuid,))
    usuario_atualizado = cursor.fetchone()
    
    return dict(usuario_atualizado)

@app.delete("/api/admin/usuarios/{uuid}")
def deletar_usuario_admin(
    uuid: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Deleta um usuário (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    if user.get("uuid") == uuid:
        raise HTTPException(status_code=400, detail="Não é possível excluir sua própria conta")
    
    cursor = db.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE uuid = ?", (uuid,))
    usuario = cursor.fetchone()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    cursor.execute("SELECT COUNT(*) as total FROM produtos WHERE usuario_uuid = ?", (uuid,))
    total_produtos = cursor.fetchone()["total"]
    
    if total_produtos > 0:
        raise HTTPException(
            status_code=400, 
            detail="Não é possível excluir usuário com produtos cadastrados"
        )
    
    cursor.execute("DELETE FROM usuarios WHERE uuid = ?", (uuid,))
    db.commit()
    
    return {"message": "Usuário excluído com sucesso"}



@app.get("/api/admin/fornecedores")
def listar_todos_fornecedores_admin(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Lista todos os fornecedores do sistema (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    
    # Query atualizada para incluir contagem de produtos
    cursor.execute("""
        SELECT 
            f.*,
            u.nome as usuario_nome,
            COUNT(p.uuid) as produtos_count
        FROM fornecedores f
        LEFT JOIN usuarios u ON f.usuario_uuid = u.uuid
        LEFT JOIN produtos p ON f.uuid = p.fornecedor_uuid
        GROUP BY f.uuid
        ORDER BY f.nome
    """)
    
    fornecedores = cursor.fetchall()
    
    return [dict(fornecedor) for fornecedor in fornecedores]

@app.get("/api/admin/produtos")
def listar_todos_produtos_admin(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Lista todos os produtos do sistema (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    cursor.execute("""
        SELECT p.*, u.nome as usuario_nome, f.nome as fornecedor_nome 
        FROM produtos p
        LEFT JOIN usuarios u ON p.usuario_uuid = u.uuid
        LEFT JOIN fornecedores f ON p.fornecedor_uuid = f.uuid
        ORDER BY p.nome
    """)
    produtos = cursor.fetchall()
    
    produtos_formatados = []
    for produto in produtos:
        produto_dict = dict(produto)
        if produto_dict["data_validade"]:
            produto_dict["data_validade"] = date.fromisoformat(produto_dict["data_validade"])
        produtos_formatados.append(produto_dict)
    
    return produtos_formatados


@app.get("/api/admin/produtos/estatisticas")
def obter_estatisticas_produtos_admin(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Obtém estatísticas de produtos (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    
    # Total de produtos
    cursor.execute("SELECT COUNT(*) as total FROM produtos")
    total_produtos = cursor.fetchone()["total"]
    
    # Produtos a vencer (próximos 7 dias)
    cursor.execute("SELECT COUNT(*) as total FROM produtos WHERE status = 'a_vencer'")
    produtos_a_vencer = cursor.fetchone()["total"]
    
    # Produtos vencidos
    cursor.execute("SELECT COUNT(*) as total FROM produtos WHERE status = 'vencido'")
    produtos_vencidos = cursor.fetchone()["total"]
    
    # Produtos esgotados
    cursor.execute("SELECT COUNT(*) as total FROM produtos WHERE status = 'esgotado'")
    produtos_esgotados = cursor.fetchone()["total"]
    
    return {
        "total_produtos": total_produtos,
        "produtos_a_vencer": produtos_a_vencer,
        "produtos_vencidos": produtos_vencidos,
        "produtos_esgotados": produtos_esgotados
    }

@app.delete("/api/admin/produtos/{uuid}")
def deletar_produto_admin(
    uuid: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Deleta um produto (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    
    # Verificar se o produto existe
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (uuid,))
    produto = cursor.fetchone()
    
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    # Deletar o produto
    cursor.execute("DELETE FROM produtos WHERE uuid = ?", (uuid,))
    db.commit()
    
    # Registrar log
    usuario_uuid = request.session["user"]["uuid"]
    detalhes = f"Produto excluído: {produto['nome']} (UUID: {uuid})"
    registrar_log(db, usuario_uuid, "Exclusão de Produto", detalhes)
    
    return {"message": "Produto excluído com sucesso"}

@app.get("/api/admin/produtos/{uuid}")
def obter_produto_admin(
    uuid: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Obtém um produto específico com informações de usuário e fornecedor (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    cursor.execute("""
        SELECT p.*, u.nome as usuario_nome, f.nome as fornecedor_nome 
        FROM produtos p
        LEFT JOIN usuarios u ON p.usuario_uuid = u.uuid
        LEFT JOIN fornecedores f ON p.fornecedor_uuid = f.uuid
        WHERE p.uuid = ?
    """, (uuid,))
    produto = cursor.fetchone()
    
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    produto_dict = dict(produto)
    if produto_dict["data_validade"]:
        produto_dict["data_validade"] = date.fromisoformat(produto_dict["data_validade"])
    
    return produto_dict



@app.get("/relatorio/logs/pdf")
def relatorio_logs_pdf(request: Request, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        return RedirectResponse("/login")

    usuario_uuid = request.session["user"]["uuid"]
    usuario_nome = request.session["user"]["nome"].replace(" ", "_")


    cursor = db.cursor()

    cursor.execute("""
        SELECT logs.data, logs.acao, logs.detalhes, usuarios.nome AS usuario_nome
        FROM logs
        JOIN usuarios ON logs.usuario_uuid = usuarios.uuid
        WHERE logs.usuario_uuid = ?
        ORDER BY logs.data DESC
    """, (usuario_uuid,))
    logs = cursor.fetchall()

    buffer_pdf = gerar_pdf_logs(logs, usuario_nome)

    return StreamingResponse(
        buffer_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="Relatorio_{usuario_nome}.pdf"'
        }
    )


@app.get("/api/admin/relatorio/logs/pdf/{usuario_uuid}")
def relatorio_logs_pdf_admin(usuario_uuid: str, request: Request, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        return RedirectResponse("/login")
    
    if request.session["user"]["tipo"] != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar este relatório.")

    cursor = db.cursor()

    # Buscar todos os logs do usuário escolhido
    cursor.execute("""
        SELECT logs.data, logs.acao, logs.detalhes, usuarios.nome AS usuario_nome
        FROM logs
        JOIN usuarios ON logs.usuario_uuid = usuarios.uuid
        WHERE logs.usuario_uuid = ?
        ORDER BY logs.data DESC
    """, (usuario_uuid,))
    logs = cursor.fetchall()

    cursor.execute("SELECT nome FROM usuarios WHERE uuid = ?", (usuario_uuid,))
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    usuario_nome = row["nome"].replace(" ", "_")

    buffer_pdf = gerar_pdf_logs(logs, usuario_nome)

    return StreamingResponse(
        buffer_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=Relatorio_{usuario_nome}.pdf"
        }
    )



@app.get("/api/debug/estatisticas")
def debug_estatisticas(request:Request, db: sqlite3.Connection = Depends(get_db)):
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    cursor = db.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM usuarios")
    total_usuarios = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE tipo = 'agricultor'")
    total_agricultores = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE tipo = 'admin'")
    total_admins = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM produtos")
    total_produtos = cursor.fetchone()["total"]
    
    return {
        "total_usuarios": total_usuarios,
        "total_agricultores": total_agricultores,
        "total_admins": total_admins,
        "total_produtos": total_produtos,
        "debug": "API funcionando"
    }

@app.get("/api/admin/estatisticas")
def obter_estatisticas_admin(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Obtém estatísticas gerais do sistema (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    
    # 1. Total de fornecedores
    cursor.execute("SELECT COUNT(*) as total FROM fornecedores")
    total_fornecedores = cursor.fetchone()["total"]
    
    # 2. Total de produtos fornecidos (todos os produtos do sistema)
    cursor.execute("SELECT COUNT(*) as total FROM produtos")
    total_produtos = cursor.fetchone()["total"]
    
    # 3. Total de entradas registradas (movimentos do tipo 'entrada')
    cursor.execute("SELECT COUNT(*) as total FROM movimentos WHERE tipo = 'entrada'")
    total_entradas = cursor.fetchone()["total"]
    
    # 4. Fornecedores ativos (fornecedores que têm produtos vinculados)
    cursor.execute("""
        SELECT COUNT(DISTINCT f.uuid) as total 
        FROM fornecedores f
        INNER JOIN produtos p ON f.uuid = p.fornecedor_uuid
    """)
    fornecedores_ativos = cursor.fetchone()["total"]
    
    # Estatísticas adicionais para o frontend
    # Total de produtos por fornecedor (média)
    cursor.execute("""
        SELECT 
            COUNT(DISTINCT f.uuid) as fornecedores_com_produtos,
            COUNT(p.uuid) as total_produtos_vinculados
        FROM fornecedores f
        LEFT JOIN produtos p ON f.uuid = p.fornecedor_uuid
    """)
    stats_produtos = cursor.fetchone()
    
    # Total de movimentos por fornecedor
    cursor.execute("""
        SELECT 
            COUNT(DISTINCT f.uuid) as fornecedores_com_movimentos,
            COUNT(m.uuid) as total_movimentos_vinculados
        FROM fornecedores f
        LEFT JOIN produtos p ON f.uuid = p.fornecedor_uuid
        LEFT JOIN movimentos m ON p.uuid = m.produto_uuid
        WHERE m.tipo = 'entrada'
    """)
    stats_movimentos = cursor.fetchone()
    
    return {
        "total_fornecedores": total_fornecedores,
        "total_produtos": total_produtos,
        "total_entradas": total_entradas,
        "fornecedores_ativos": fornecedores_ativos,
        "estatisticas_adicionais": {
            "media_produtos_por_fornecedor": round(
                stats_produtos["total_produtos_vinculados"] / max(stats_produtos["fornecedores_com_produtos"], 1), 
                1
            ) if stats_produtos else 0,
            "media_movimentos_por_fornecedor": round(
                stats_movimentos["total_movimentos_vinculados"] / max(stats_movimentos["fornecedores_com_movimentos"], 1), 
                1
            ) if stats_movimentos else 0
        }
    }

@app.get("/api/admin/fornecedores/detalhados")
def listar_fornecedores_detalhados_admin(
    request: Request,
    db: sqlite3.Connection = Depends(get_db)
):
    """Lista todos os fornecedores com estatísticas detalhadas (apenas para administradores)"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    user = request.session["user"]
    if user.get("tipo") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    cursor = db.cursor()
    
    # Query para obter fornecedores com contagem de produtos e movimentos
    cursor.execute("""
        SELECT 
            f.uuid,
            f.nome,
            f.telefone,
            f.email,
            f.usuario_uuid,
            u.nome as usuario_nome,
            COUNT(DISTINCT p.uuid) as produtos_count,
            COUNT(DISTINCT CASE WHEN m.tipo = 'entrada' THEN m.uuid END) as entradas_count,
            COUNT(DISTINCT CASE WHEN m.tipo = 'saida' THEN m.uuid END) as saidas_count,
            COUNT(DISTINCT p.usuario_uuid) as usuarios_count
        FROM fornecedores f
        LEFT JOIN usuarios u ON f.usuario_uuid = u.uuid
        LEFT JOIN produtos p ON f.uuid = p.fornecedor_uuid
        LEFT JOIN movimentos m ON p.uuid = m.produto_uuid
        GROUP BY f.uuid
        ORDER BY f.nome
    """)
    
    fornecedores = cursor.fetchall()
    
    return [dict(fornecedor) for fornecedor in fornecedores]

