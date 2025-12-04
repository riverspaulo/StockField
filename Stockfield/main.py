#pip install fastapi uvicorn pydantic
#uvicorn main:app

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

from models import Produto, Usuario, Fornecedor, Movimento, init_db, get_db, TipoUsuario, TipoMovimento, StatusProduto

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="chave_super_secreta")
init_db()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

ALERTA_DIAS = 7  # Dias para considerar produto "a vencer"

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
    cursor.execute("SELECT * FROM usuarios WHERE cnpj = ? AND senha = ?", (cnpj, senha))
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

    # VERIFICAÇÃO DE ALERTAS DE ESTOQUE BAIXO
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
    
    # ============ VERIFICAÇÃO AUTOMÁTICA DE ALERTAS AO LOGIN ============
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
    
    # ============ VERIFICAÇÃO DE TIPO DE USUÁRIO ============
    # Se for administrador, redireciona para página específica
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

    novo_uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?, ?)",
        (novo_uuid, cnpj, nome, email, senha, tipo_usuario)
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


#MAIS UMA MATEUSSSSSSSSSS
@app.post("/movimentos/entrada", response_model=Movimento)
def registrar_entrada(movimento: Movimento, request: Request, db: sqlite3.Connection = Depends(get_db)):
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
    usuario_uuid = request.session["user"]["uuid"]
    alertas_estoque = verificar_estoque_baixo(db, usuario_uuid)
    
    if alertas_estoque:
        request.session["alertas_estoque"] = {
            "total": len(alertas_estoque),
            "data_verificacao": date.today().isoformat()
        }
    
    db.commit()
    return movimento


#MATEUSSSSSSSSSSSSSSSSSSSS
@app.post("/movimentos/saida", response_model=Movimento)
def registrar_saida(movimento: Movimento, request: Request, db: sqlite3.Connection = Depends(get_db)):
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
    usuario_uuid = request.session["user"]["uuid"]
    alertas_estoque = verificar_estoque_baixo(db, usuario_uuid)
    
    # Opcional: você pode armazenar os alertas na sessão
    if alertas_estoque:
        request.session["alertas_estoque"] = {
            "total": len(alertas_estoque),
            "data_verificacao": date.today().isoformat()
        }
    
    
    db.commit()
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
    
    cursor.execute(
        "INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",  
        (
            produto.uuid,                    # 1
            produto.nome,                    # 2
            produto.descricao,               # 3
            produto.categoria,               # 4
            produto.tipo_produto.value,      # 5
            produto.numero_anvisa,           # 6
            produto.cuidados_armazenamento,  # 7
            produto.tipo_toxico,             # 8
            produto.quantidade,              # 9
            produto.estoque_minimo,          # 10
            produto.preco_unitario,          # 11
            produto.data_validade.isoformat() if produto.data_validade else None,  # 12
            produto.lote,                    # 13
            produto.fornecedor_uuid,         # 14
            produto.localizacao,             # 15
            produto.status.value,            # 16
            usuario_uuid,                    # 17
            dias_para_vencer,                # 18 
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
def listar_produtos(request: Request, db: sqlite3.Connection = Depends(get_db)):
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
    fornecedores = [Fornecedor(**dict(row)) for row in cursor.fetchall()]
    return fornecedores


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

@app.put("/fornecedores/{uuid}", response_model=Fornecedor)
def atualizar_fornecedor(uuid: str, fornecedor: Fornecedor, db: sqlite3.Connection = Depends(get_db)):
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
def deletar_fornecedor(uuid: str, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM fornecedores WHERE uuid = ?", (uuid,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
   
    cursor.execute("SELECT * FROM produtos WHERE fornecedor_uuid = ?", (uuid,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="Não é possível excluir fornecedor com produtos vinculados")
    
    cursor.execute("DELETE FROM fornecedores WHERE uuid = ?", (uuid,))
    db.commit()
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
            nome = ?, descricao = ?, categoria = ?, tipo_produto = ?,
            numero_anvisa = ?, cuidados_armazenamento = ?, tipo_toxico = ?,
            quantidade = ?, estoque_minimo = ?, preco_unitario = ?, data_validade = ?, lote = ?, 
            fornecedor_uuid = ?, localizacao = ?, status = ? 
        WHERE uuid = ?""",
        (
            produto.nome,
            produto.descricao,
            produto.categoria,
            produto.tipo_produto.value,
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
def obter_produto_edicao(uuid: str, db: sqlite3.Connection = Depends(get_db)):
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
    
    return {
        "total_usuarios": total_usuarios,
        "total_agricultores": total_agricultores,
        "total_admins": total_admins
    }

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
    flash(request, "Você saiu do sistema.", "info")
    url = request.url_for("login")
    return RedirectResponse(url=url, status_code=303)