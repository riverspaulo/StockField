from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from typing import List
import uuid
import sqlite3
import os

from models import Produto, Usuario, Fornecedor, init_db, get_db

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

    flash(request, f"Bem-vindo(a), {user['nome']}!", "success")
    url = request.url_for("index")
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

    novo_uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?, ?)",
        (novo_uuid, cnpj, nome, email, senha, tipo_usuario)
    )
    db.commit()
    flash(request, "Cadastro realizado com sucesso!", "success")
    url = request.url_for("index")
    return RedirectResponse(url=url, status_code=303)

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
            produto.data_validade,
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
    return [Produto(**dict(row)) for row in cursor.fetchall()]

@app.get("/produtos/{nome}", response_model=Produto)
def obter_produto(nome: str, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE nome = ?", (nome,))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return Produto(**dict(produto))

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
