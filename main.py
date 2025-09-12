from fastapi import FastAPI, HTTPException
from models import Produto, Usuario
from typing import List

app = FastAPI()

produtos: List[Produto] = []
usuarios: List[Usuario] = []

@app.get("/produtos")
def listar_produtos():
    return {"produtos": produtos}

@app.post("/produtos")
def adicionar_produto(produto: Produto):
    produtos.append(produto)
    return {"mensagem": "Produto adicionado", "produto": produto}

@app.get("/produtos/{produto_nome}")
def obter_produto(produto_nome: str):
    for produto in produtos:
        if produto.nome.lower() == produto_nome.lower():
            return produto
    raise HTTPException(status_code=404, detail="Produto não encontrado")


@app.post("/usuarios")
def adicionar_usuario(usuario: Usuario):
    usuarios.append(usuario)
    return {"mensagem": "Usuário adicionado", "usuario": usuario}