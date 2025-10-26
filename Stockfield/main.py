from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from typing import List
from datetime import date
import uuid
import sqlite3
import os

from models import Produto, Usuario, Fornecedor, Movimento, init_db, get_db, TipoUsuario, TipoMovimento

app = FastAPI()

app.add_middleware(SessionMiddleware, secret_key="chave_super_secreta")
init_db()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def flash(request: Request, message: str, category: str = "info"):
    if "messages" not in request.session:
        request.session["messages"] = []
    request.session["messages"].append({"message": message, "category": category})

def get_flashed_messages(request: Request):
    messages = request.session.pop("messages") if "messages" in request.session else []
    return messages

# Rotas de templates

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "messages": get_flashed_messages(request)})

@app.get("/login", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "messages": get_flashed_messages(request)})

@app.post("/login")
def login_action(
    request: Request,
    cnpj: str = Form(...),
    senha: str = Form(...),
    db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE cnpj = ? AND senha = ?", (cnpj, senha))
    user = cursor.fetchone()

    if not user:
        flash(request, "CNPJ ou senha inválidos.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)

    # Armazenar informações do usuário na sessão
    request.session["user"] = {
        "uuid": user["uuid"],
        "nome": user["nome"],
        "email": user["email"],
        "tipo": user["tipo"]
    }
    
    flash(request, f"Bem-vindo(a), {user['nome']}!", "success")
    # Redirecionar para a página de perfil
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
    
    # Verificar se email já existe
    cursor.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
    if cursor.fetchone():
        flash(request, "E-mail já cadastrado!", "error")
        url = request.url_for("cadastro")
        return RedirectResponse(url=url, status_code=303)
    
    # Verificar se CNPJ já existe
    cursor.execute("SELECT * FROM usuarios WHERE cnpj = ?", (cnpj,))
    if cursor.fetchone():
        flash(request, "CNPJ já cadastrado!", "error")
        url = request.url_for("cadastro")
        return RedirectResponse(url=url, status_code=303)

    # Verificar se o tipo de usuário é válido
    tipos_validos = [tipo.value for tipo in TipoUsuario]
    if tipo_usuario not in tipos_validos:
        flash(request, "Tipo de usuário inválido!", "error")
        url = request.url_for("cadastro")
        return RedirectResponse(url=url, status_code=303)

    novo_uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?, ?)",
        (novo_uuid, cnpj, nome, email, senha, tipo_usuario)
    )
    db.commit()
    flash(request, "Cadastro realizado com sucesso! Faça login para continuar.", "success")
    # Redirecionar para a página de login após o cadastro
    url = request.url_for("login")
    return RedirectResponse(url=url, status_code=303)

# Nova rota para a página de perfil
@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    # Verificar se o usuário está logado
    if "user" not in request.session:
        flash(request, "Você precisa fazer login para acessar esta página.", "error")
        url = request.url_for("login")
        return RedirectResponse(url=url, status_code=303)
    
    return templates.TemplateResponse("profile.html", {
        "request": request, 
        "messages": get_flashed_messages(request),
        "user": request.session["user"]
    })

# Rotas de Movimentações


@app.get("/movimentos/", response_model=List[Movimento])
def listar_movimentos(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        SELECT m.*, p.nome as produto_nome, f.nome as fornecedor_nome 
        FROM movimentos m
        LEFT JOIN produtos p ON m.produto_uuid = p.uuid
        LEFT JOIN fornecedores f ON m.fornecedor_uuid = f.uuid
        ORDER BY m.data DESC
    """)
    movimentos_data = cursor.fetchall()
    
    movimentos = []
    for row in movimentos_data:
        movimento_dict = dict(row)
        # Manter compatibilidade com o modelo Movimento
        movimento_dict["data"] = date.fromisoformat(movimento_dict["data"])
        movimento = Movimento(**{k: v for k, v in movimento_dict.items() if k in Movimento.__fields__})
        movimentos.append(movimento)
    
    return movimentos

# Adicione também uma rota para obter informações detalhadas de um produto
@app.get("/produtos/{uuid}", response_model=Produto)
def obter_produto_por_uuid(uuid: str, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (uuid,))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    produto_dict = dict(produto)
    if produto_dict["data_validade"]:
        produto_dict["data_validade"] = date.fromisoformat(produto_dict["data_validade"])
    return Produto(**produto_dict)

@app.post("/movimentos/entrada", response_model=Movimento)
def registrar_entrada(movimento: Movimento, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    
    # Verificar se o produto existe
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (movimento.produto_uuid,))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    # Verificar se o fornecedor existe
    cursor.execute("SELECT * FROM fornecedores WHERE uuid = ?", (movimento.fornecedor_uuid,))
    fornecedor = cursor.fetchone()
    if not fornecedor:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
    
    # Registrar o movimento
    movimento.uuid = str(uuid.uuid4())
    movimento.tipo = TipoMovimento.entrada
    
    cursor.execute(
        "INSERT INTO movimentos VALUES (?, ?, ?, ?, ?, ?)",
        (
            movimento.uuid,
            movimento.produto_uuid,
            movimento.tipo.value,
            movimento.quantidade,
            movimento.data.isoformat(),
            movimento.fornecedor_uuid
        )
    )
    
    # Atualizar o estoque do produto (somar quantidade)
    nova_quantidade = produto["quantidade"] + movimento.quantidade
    
    # Atualizar status baseado na nova quantidade
    novo_status = "disponível" if nova_quantidade > 0 else "esgotado"
    
    cursor.execute(
        "UPDATE produtos SET quantidade = ?, status = ? WHERE uuid = ?",
        (nova_quantidade, novo_status, movimento.produto_uuid)
    )
    
    db.commit()
    return movimento

@app.post("/movimentos/saida", response_model=Movimento)
def registrar_saida(movimento: Movimento, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    
    # Verificar se o produto existe
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (movimento.produto_uuid,))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    # Verificar se há estoque suficiente
    if produto["quantidade"] < movimento.quantidade:
        raise HTTPException(status_code=400, detail="Estoque insuficiente")
    
    # Verificar se o fornecedor existe
    cursor.execute("SELECT * FROM fornecedores WHERE uuid = ?", (movimento.fornecedor_uuid,))
    fornecedor = cursor.fetchone()
    if not fornecedor:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
    
    # Registrar o movimento
    movimento.uuid = str(uuid.uuid4())
    movimento.tipo = TipoMovimento.saida
    
    cursor.execute(
        "INSERT INTO movimentos VALUES (?, ?, ?, ?, ?, ?)",
        (
            movimento.uuid,
            movimento.produto_uuid,
            movimento.tipo.value,
            movimento.quantidade,
            movimento.data.isoformat(),
            movimento.fornecedor_uuid
        )
    )
    
    # Atualizar o estoque do produto (subtrair quantidade)
    nova_quantidade = produto["quantidade"] - movimento.quantidade
    
    # Atualizar status baseado na nova quantidade
    novo_status = "disponível" if nova_quantidade > 0 else "esgotado"
    
    cursor.execute(
        "UPDATE produtos SET quantidade = ?, status = ? WHERE uuid = ?",
        (nova_quantidade, novo_status, movimento.produto_uuid)
    )
    
    db.commit()
    return movimento

# Rotas de API

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
def cadastrar_produto(produto: Produto, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    produto.uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            produto.uuid,
            produto.nome,
            produto.descricao,
            produto.categoria,
            produto.quantidade,
            produto.preco_unitario,
            produto.data_validade.isoformat() if produto.data_validade else None,
            produto.lote,
            produto.fornecedor_uuid,
            produto.localizacao,
            produto.status.value
        )
    )
    db.commit()
    return produto

@app.post("/fornecedores/", response_model=Fornecedor)
def cadastrar_fornecedor(fornecedor: Fornecedor, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    fornecedor.uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO fornecedores VALUES (?, ?, ?, ?)",
        (fornecedor.uuid, fornecedor.nome, fornecedor.telefone, fornecedor.email)
    )
    db.commit()
    return fornecedor

@app.get("/produtos/", response_model=List[Produto])
def listar_produtos(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos")
    produtos = []
    for row in cursor.fetchall():
        produto_dict = dict(row)
        if produto_dict["data_validade"]:
            produto_dict["data_validade"] = date.fromisoformat(produto_dict["data_validade"])
        produtos.append(Produto(**produto_dict))
    return produtos

@app.get("/produtos/{nome}", response_model=Produto)
def obter_produto(nome: str, db: sqlite3.Connection = Depends(get_db)):
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
def deletar_produto(uuid: str, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (uuid,))
    produto = cursor.fetchone()
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    cursor.execute("DELETE FROM produtos WHERE uuid = ?", (uuid,))
    db.commit()
    return {"message": "Produto deletado com sucesso"}

@app.get("/fornecedores/", response_model=List[Fornecedor])
def listar_fornecedores(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM fornecedores")
    return [Fornecedor(**dict(row)) for row in cursor.fetchall()]